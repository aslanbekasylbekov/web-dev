from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category, Subscription
from ..schemas import BillingCycle, CategoryCreate, CategoryOut, CategoryPatch, Currency, Page, SubscriptionOut
from .common import commit_or_409, conflict, get_or_404, not_found, order_by, paginate, validate_merged
from .subscriptions import SUBSCRIPTION_SORT, SUBSCRIPTION_SORT_DESCRIPTION, subscription_list_query

router = APIRouter(prefix="/categories", tags=["categories"])

WRITABLE_FIELDS = tuple(CategoryCreate.model_fields)
CATEGORY_SORT = {
    "id": Category.id,
    "name": Category.name,
    "created_at": Category.created_at,
    "subscription_count": Category.subscription_count,
}

CATEGORY_404 = not_found("Category not found")
NAME_409 = conflict("A category with this name already exists")


def _ensure_unique_name(db: Session, name: str, exclude_id: int | None) -> None:
    stmt = select(Category.id).where(func.lower(Category.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Category.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise HTTPException(status_code=409, detail=f"Category '{name}' already exists")


def _save(db: Session, category: Category, payload: CategoryCreate) -> Category:
    _ensure_unique_name(db, payload.name, exclude_id=category.id)
    for key, value in payload.model_dump().items():
        setattr(category, key, value)
    db.add(category)
    commit_or_409(db, f"Category '{payload.name}' already exists")
    db.refresh(category)
    return category


@router.get(
    "",
    response_model=Page[CategoryOut],
    summary="List categories",
    description="Sort fields: " + ", ".join(sorted(CATEGORY_SORT)) + ". Prefix with '-' for descending.",
)
def list_categories(
    q: str | None = Query(None, min_length=1, description="Case-insensitive search in name and description"),
    sort: str = Query("name", description="Sort field, prefix with '-' for descending"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Category)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(Category.name.ilike(pattern), Category.description.ilike(pattern)))
    return paginate(db, stmt, order_by(sort, CATEGORY_SORT, Category.id), limit, offset)


@router.post(
    "",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    responses=NAME_409,
    summary="Create a category",
    description="`name` is unique, case-insensitive (`Streaming` = `streaming`).",
)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    return _save(db, Category(), payload)


@router.get("/{category_id}", response_model=CategoryOut, responses=CATEGORY_404, summary="Get a category")
def get_category(category_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Category, category_id, "Category")


@router.put(
    "/{category_id}",
    response_model=CategoryOut,
    responses={**CATEGORY_404, **NAME_409},
    summary="Replace a category (full update)",
    description="Same body as POST. `description` is cleared if omitted.",
)
def replace_category(category_id: int, payload: CategoryCreate, db: Session = Depends(get_db)):
    category = get_or_404(db, Category, category_id, "Category")
    return _save(db, category, payload)


@router.patch(
    "/{category_id}",
    response_model=CategoryOut,
    responses={**CATEGORY_404, **NAME_409},
    summary="Update a category (partial)",
    description="Send only the fields to change. The result is validated with the same rules as POST.",
)
def update_category(category_id: int, payload: CategoryPatch, db: Session = Depends(get_db)):
    category = get_or_404(db, Category, category_id, "Category")
    current = {field: getattr(category, field) for field in WRITABLE_FIELDS}
    full = validate_merged(CategoryCreate, current, payload.model_dump(exclude_unset=True))
    return _save(db, category, full)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**CATEGORY_404, **conflict("The category still has subscriptions")},
    summary="Delete a category",
    description="Only an empty category can be deleted. If it still has subscriptions the API answers `409`: "
                "move them to another category (PATCH `category_id`) or delete them first.",
)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    category = get_or_404(db, Category, category_id, "Category")
    if category.subscription_count:
        raise HTTPException(
            status_code=409,
            detail=f"Category '{category.name}' still has {category.subscription_count} subscription(s); "
                   "move or delete them first",
        )
    db.delete(category)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- related data: subscriptions of a category

@router.get(
    "/{category_id}/subscriptions",
    response_model=Page[SubscriptionOut],
    responses=CATEGORY_404,
    summary="Subscriptions of a category",
    description="Same filters as GET /subscriptions, limited to one category.",
)
def list_category_subscriptions(
    category_id: int,
    currency: Currency | None = Query(None),
    billing_cycle: BillingCycle | None = Query(None),
    active: bool | None = Query(None, description="true = active, false = cancelled"),
    min_price: Decimal | None = Query(None, ge=0),
    max_price: Decimal | None = Query(None, ge=0),
    q: str | None = Query(None, min_length=1),
    sort: str = Query("name", description=SUBSCRIPTION_SORT_DESCRIPTION),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    get_or_404(db, Category, category_id, "Category")
    stmt = subscription_list_query(
        category_id=category_id, currency=currency, billing_cycle=billing_cycle, active=active,
        min_price=min_price, max_price=max_price, q=q,
    )
    return paginate(db, stmt, order_by(sort, SUBSCRIPTION_SORT, Subscription.id), limit, offset)
