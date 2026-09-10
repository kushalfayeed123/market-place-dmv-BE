# app/core/logging.py
"""
Logging configuration following the Stoxava pattern:
JSON formatter with correlation IDs for request tracing.
"""

import logging
import sys
from pythonjsonlogger import jsonlogger
import uuid
from typing import Optional

# Global variable to store correlation ID
_correlation_id: Optional[str] = None

def set_correlation_id(cid: str):
    """Set the correlation ID for the current context."""
    global _correlation_id
    _correlation_id = cid

def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID."""
    return _correlation_id

class CorrelationIDFilter(logging.Filter):
    """Logging filter to add correlation ID to log records."""
    
    def filter(self, record):
        record.correlation_id = get_correlation_id() or ""
        return True

class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter that includes correlation ID and timestamp."""
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        if not log_record.get('timestamp'):
            log_record['timestamp'] = record.created
        if record.levelname:
            log_record['level'] = record.levelname
        if record.name:
            log_record['logger'] = record.name
        # Add correlation ID if present
        if getattr(record, 'correlation_id', None):
            log_record['correlation_id'] = record.correlation_id

def setup_logging():
    """Setup application logging with JSON formatting and correlation IDs."""
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = CustomJsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s %(correlation_id)s'
    )
    
    # Add correlation ID filter
    correlation_filter = CorrelationIDFilter()
    console_handler.addFilter(correlation_filter)
    
    # Set formatter
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    # Prevent duplicate logs
    logger.propagate = False
    
    # Configure specific loggers
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    return logger

# Dependency for FastAPI to set correlation ID per request
async def correlation_id_middleware(request, call_next):
    """Middleware to generate and set correlation ID for each request."""
    # Generate or extract correlation ID
    cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    set_correlation_id(cid)
    
    # Process request
    response = await call_next(request)
    
    # Add correlation ID to response headers
    response.headers["X-Correlation-ID"] = cid
    
    # Clear correlation ID after request
    set_correlation_id(None)
    
    return response