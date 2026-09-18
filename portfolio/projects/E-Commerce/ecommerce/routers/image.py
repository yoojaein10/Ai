from fastapi import APIRouter, Depends

from services.image_service import ImageService, get_image_service

router = APIRouter(prefix="/image", tags=["Image"])


@router.post("/rehost")
async def rehost_images(
    image_urls: list[str],
    image_svc: ImageService = Depends(get_image_service),
):
    rehosted = await image_svc.download_and_rehost(image_urls)
    return {"images": rehosted}
