# scripts/db/seed.py
"""
Seed data for local development.
Run with: python -m scripts.db.seed
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.commission_plan import CommissionPlan
from app.models.merchant import Merchant
from app.models.user import User, UserRole, UserStatus


async def seed_commission_plans(db: AsyncSession) -> None:
    """Seed default commission plans."""
    plans = [
        CommissionPlan(
            name="Standard Commission",
            percentage_bps=1000,  # 10%
            flat_fee_minor=0,
            currency="NGN",
            is_default=True,
        ),
        CommissionPlan(
            name="Premium Commission",
            percentage_bps=500,  # 5%
            flat_fee_minor=0,
            currency="NGN",
            is_default=False,
        ),
        CommissionPlan(
            name="Enterprise Commission",
            percentage_bps=250,  # 2.5%
            flat_fee_minor=10000,  # 100 NGN flat fee
            currency="NGN",
            is_default=False,
        ),
    ]

    for plan in plans:
        result = await db.execute(
            select(CommissionPlan).where(CommissionPlan.name == plan.name)
        )
        if result.scalar_one_or_none() is None:
            db.add(plan)
            print(f"Created commission plan: {plan.name}")

    await db.commit()


async def seed_admin_user(db: AsyncSession) -> None:
    """Seed default admin user."""
    admin_email = "admin@marketplace.local"

    result = await db.execute(select(User).where(User.email == admin_email))
    if result.scalar_one_or_none() is None:
        admin = User(
            email=admin_email,
            password_hash=get_password_hash("admin123"),
            role=UserRole.PLATFORM_ADMIN,
            status=UserStatus.ACTIVE,
            phone="+2340000000000",
        )
        db.add(admin)
        print(f"Created admin user: {admin_email}")
    else:
        print(f"Admin user already exists: {admin_email}")

    await db.commit()


async def seed_test_users(db: AsyncSession) -> None:
    """Seed test users for development."""
    test_users = [
        {"email": "buyer@marketplace.local", "role": UserRole.BUYER, "password": "buyer123", "phone": "+2340000000001"},
        {"email": "merchant@marketplace.local", "role": UserRole.MERCHANT_OWNER, "password": "merchant123", "phone": "+2340000000002"},
    ]

    for user_data in test_users:
        result = await db.execute(
            select(User).where(User.email == user_data["email"])
        )
        if result.scalar_one_or_none() is None:
            user = User(
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                role=user_data["role"],
                status=UserStatus.ACTIVE,
                phone=user_data["phone"],
            )
            db.add(user)
            print(f"Created test user: {user_data['email']}")
        else:
            print(f"Test user already exists: {user_data['email']}")

    await db.commit()


async def seed_merchants(db: AsyncSession) -> None:
    """Seed sample merchants for development."""
    # Get the admin user to be the owner
    admin_result = await db.execute(
        select(User).where(User.email == "admin@marketplace.local")
    )
    admin = admin_result.scalar_one_or_none()

    if not admin:
        print("Skipping merchant seeding - no admin user found")
        return

    # Get the default commission plan
    plan_result = await db.execute(
        select(CommissionPlan).where(CommissionPlan.is_default == True)
    )
    default_plan = plan_result.scalar_one_or_none()

    if not default_plan:
        print("Skipping merchant seeding - no default commission plan found")
        return

    merchants = [
        {
            "owner_user_id": admin.id,
            "business_name": "Uncle Seg's Tech Gadgets",
            "slug": "unclesegs-tech-gadgets",
            "commission_plan_id": default_plan.id,
        },
    ]

    for merchant_data in merchants:
        result = await db.execute(
            select(Merchant).where(Merchant.slug == merchant_data["slug"])
        )
        if result.scalar_one_or_none() is None:
            merchant = Merchant(**merchant_data)
            db.add(merchant)
            print(f"Created merchant: {merchant_data['business_name']}")
        else:
            print(f"Merchant already exists: {merchant_data['business_name']}")

    await db.commit()


async def main() -> None:
    """Run all seed functions."""
    print("=== Seeding Database ===")

    async with AsyncSessionLocal() as db:
        await seed_commission_plans(db)
        await seed_admin_user(db)
        await seed_test_users(db)
        await seed_merchants(db)

    print("=== Seeding Complete ===")
    print("\nDefault credentials:")
    print("  Admin: admin@marketplace.local / admin123")
    print("  Buyer: buyer@marketplace.local / buyer123")
    print("  Merchant: merchant@marketplace.local / merchant123")


if __name__ == "__main__":
    asyncio.run(main())