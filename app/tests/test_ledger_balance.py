"""Regression tests for merchant balance derivation (get_balance).

Reproduces the production symptom: ledger entries exist (sale/commission on
platform_revenue + payout_hold on merchant_wallet), yet the balance endpoint
returned all zeros — and could go negative while a hold was unreleased.
"""

import uuid

import pytest

from app.models.commission_plan import CommissionPlan
from app.models.ledger_entry import (
    LedgerAccountType,
    LedgerDirection,
    LedgerEntry,
    LedgerEntryType,
)
from app.models.merchant import KycStatus, Merchant
from app.models.user import Gender, User, UserRole
from app.modules.ledger.service.implementation import LedgerServiceImpl


@pytest.fixture
async def merchant_with_plan(db):
    plan = CommissionPlan(name="default", percentage_bps=1000, flat_fee_minor=0, is_default=True)
    db.add(plan)
    await db.flush()
    owner = User(
        email="balance-merchant@example.com",
        password_hash="x",
        role=UserRole.MERCHANT_OWNER,
        first_name="B",
        last_name="M",
        gender=Gender.UNSET,
    )
    db.add(owner)
    await db.flush()
    merchant = Merchant(
        owner_user_id=owner.id,
        business_name="Balance Merchant",
        slug="balance-merchant-" + uuid.uuid4().hex[:8],
        kyc_status=KycStatus.VERIFIED,
        commission_plan_id=plan.id,
        country="NG",
    )
    db.add(merchant)
    await db.commit()
    return merchant


def _entry(merchant, account_type, direction, entry_type, amount, supersedes=None, currency="NGN"):
    return LedgerEntry(
        entry_group_id=uuid.uuid4(),
        account_type=account_type,
        merchant_id=merchant.id,
        direction=direction,
        entry_type=entry_type,
        amount=amount,
        currency=currency,
        supersedes_entry_id=supersedes,
        created_by="system",
    )


async def _post_sale(db, merchant, order_id, gross=10000, commission=500):
    """Post the same rows post_order_ledger_entries writes for one item."""
    db.add(_entry(merchant, LedgerAccountType.PLATFORM_REVENUE.value, LedgerDirection.DEBIT.value, LedgerEntryType.SALE.value, gross))
    db.add(_entry(merchant, LedgerAccountType.PLATFORM_REVENUE.value, LedgerDirection.CREDIT.value, LedgerEntryType.COMMISSION.value, commission))
    hold = _entry(merchant, LedgerAccountType.MERCHANT_WALLET.value, LedgerDirection.CREDIT.value, LedgerEntryType.PAYOUT_HOLD.value, gross - commission)
    db.add(hold)
    await db.flush()
    return hold


@pytest.mark.asyncio
async def test_balance_counts_wallet_not_platform_revenue(db, merchant_with_plan):
    """sale/commission rows carry merchant_id but must NOT affect the merchant balance."""
    service = LedgerServiceImpl(db)
    await _post_sale(db, merchant_with_plan, uuid.uuid4(), gross=10000, commission=500)
    await db.commit()

    balance = await service.get_balance(str(merchant_with_plan.id), user_id="u", user_role="merchant_owner")

    # Only the 9500 wallet hold counts — not the -10000/+500 platform rows.
    assert balance.total_balance == 9500
    assert balance.held_balance == 9500
    assert balance.available_balance == 0
    assert balance.currency == "NGN"


@pytest.mark.asyncio
async def test_balance_after_release_supersedes_hold(db, merchant_with_plan):
    """A payout_release superseding the hold moves funds from held to available."""
    service = LedgerServiceImpl(db)
    hold = await _post_sale(db, merchant_with_plan, uuid.uuid4())
    db.add(_entry(
        merchant_with_plan,
        LedgerAccountType.MERCHANT_WALLET.value,
        LedgerDirection.CREDIT.value,
        LedgerEntryType.PAYOUT_RELEASE.value,
        9500,
        supersedes=hold.id,
    ))
    await db.commit()

    balance = await service.get_balance(str(merchant_with_plan.id), user_id="u", user_role="merchant_owner")

    assert balance.total_balance == 9500
    assert balance.held_balance == 0
    assert balance.available_balance == 9500


@pytest.mark.asyncio
async def test_balance_accumulates_across_orders_and_never_negative(db, merchant_with_plan):
    """Two confirmed+released orders accumulate (2 × 9500); balance never goes negative."""
    service = LedgerServiceImpl(db)
    for _ in range(2):
        hold = await _post_sale(db, merchant_with_plan, uuid.uuid4())
        db.add(_entry(
            merchant_with_plan,
            LedgerAccountType.MERCHANT_WALLET.value,
            LedgerDirection.CREDIT.value,
            LedgerEntryType.PAYOUT_RELEASE.value,
            9500,
            supersedes=hold.id,
        ))
    await db.commit()

    balance = await service.get_balance(str(merchant_with_plan.id), user_id="u", user_role="merchant_owner")

    assert balance.total_balance == 19000
    assert balance.held_balance == 0
    assert balance.available_balance == 19000
    assert balance.total_balance >= 0


@pytest.mark.asyncio
async def test_balance_reduced_by_payout_paid_debit(db, merchant_with_plan):
    """Payouts are only on request: a payout_paid debit reduces available balance."""
    service = LedgerServiceImpl(db)
    hold = await _post_sale(db, merchant_with_plan, uuid.uuid4())
    db.add(_entry(
        merchant_with_plan,
        LedgerAccountType.MERCHANT_WALLET.value,
        LedgerDirection.CREDIT.value,
        LedgerEntryType.PAYOUT_RELEASE.value,
        9500,
        supersedes=hold.id,
    ))
    # Merchant requests a payout of 4000 → debit wallet
    db.add(_entry(
        merchant_with_plan,
        LedgerAccountType.MERCHANT_WALLET.value,
        LedgerDirection.DEBIT.value,
        LedgerEntryType.PAYOUT_PAID.value,
        4000,
    ))
    await db.commit()

    balance = await service.get_balance(str(merchant_with_plan.id), user_id="u", user_role="merchant_owner")

    assert balance.total_balance == 5500
    assert balance.held_balance == 0
    assert balance.available_balance == 5500
