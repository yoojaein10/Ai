from fastapi import APIRouter, Depends

from schemas.product_schema import UploadRequest, UploadResponse
from services.upload_service import UploadService, get_upload_service

router = APIRouter(prefix="/upload", tags=["Upload"])


@router.post("/", response_model=UploadResponse)
async def upload_product(
    request: UploadRequest,
    upload_svc: UploadService = Depends(get_upload_service),
):
    product = request.model_dump(exclude={"platform"})
    result = await upload_svc.upload(request.platform, product)
    return result
