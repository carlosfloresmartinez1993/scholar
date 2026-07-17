"""Student photo: upload (jpeg/png only, ≤5MB) then fetch the stream back."""
from tests.conftest import login
from tests.test_treasury_documents import make_student

# 1x1 transparent PNG
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


async def test_upload_then_fetch_photo(client, seed):
    await login(client)
    student = await make_student(client, str(seed["campus"].id))

    # no photo yet
    response = await client.get(f"/api/v1/students/{student['id']}/photo")
    assert response.status_code == 404
    assert student["has_photo"] is False

    response = await client.post(
        f"/api/v1/students/{student['id']}/photo",
        files={"file": ("foto.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_photo"] is True

    response = await client.get(f"/api/v1/students/{student['id']}/photo")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG_BYTES

    # non-image uploads are rejected
    response = await client.post(
        f"/api/v1/students/{student['id']}/photo",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 415
