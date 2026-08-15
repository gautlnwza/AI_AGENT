"""Items routes — example resource scaffold."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, DBSession
from app.schemas.item import ItemCreate, ItemList, ItemRead, ItemUpdate
from app.services.item import ItemService

router = APIRouter()


def get_item_service(db: DBSession) -> ItemService:
    return ItemService(db)


ItemSvc = Annotated[ItemService, Depends(get_item_service)]


@router.get("", response_model=ItemList)
async def list_items(
    service: ItemSvc,
    user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    items, total = await service.list(owner_id=user.id, skip=skip, limit=limit)
    return ItemList(items=items, total=total)


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(data: ItemCreate, service: ItemSvc, user: CurrentUser) -> Any:
    return await service.create(owner_id=user.id, data=data)


@router.get("/{item_id}", response_model=ItemRead)
async def get_item(item_id: UUID, service: ItemSvc, user: CurrentUser) -> Any:
    return await service.get(item_id=item_id, owner_id=user.id)


@router.patch("/{item_id}", response_model=ItemRead)
async def update_item(item_id: UUID, data: ItemUpdate, service: ItemSvc, user: CurrentUser) -> Any:
    return await service.update(item_id=item_id, owner_id=user.id, data=data)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_item(item_id: UUID, service: ItemSvc, user: CurrentUser) -> None:
    await service.delete(item_id=item_id, owner_id=user.id)
