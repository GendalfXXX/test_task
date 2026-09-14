from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from app.worker.processor import ImageProcessor


@pytest.fixture
def processor() -> ImageProcessor:
    """Создаёт процессор изображения."""
    return ImageProcessor()


def test_converts_transparent_png_and_resizes_it(
    processor: ImageProcessor,
) -> None:
    """Проверяет конвертацию PNG и применение параметров."""
    source = BytesIO()
    Image.new(
        mode="RGBA",
        size=(4, 2),
        color=(255, 0, 0, 128),
    ).save(source, format="PNG")

    result = processor.convert_to_jpeg(
        content=source.getvalue(),
        quality=80,
        target_width=2,
        target_height=3,
    )

    with Image.open(BytesIO(result.content)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (2, 3)

    assert result.width == 2
    assert result.height == 3
    assert result.size_bytes == len(result.content)
    assert result.quality == 80


def test_keeps_dimensions_when_parameters_are_missing(
    processor: ImageProcessor,
) -> None:
    """Проверяет сохранение исходного JPEG без параметров."""
    source = BytesIO()
    Image.new("RGB", (5, 7), "blue").save(
        source,
        format="JPEG",
    )
    original = source.getvalue()

    result = processor.convert_to_jpeg(
        content=original,
        quality=None,
        target_width=None,
        target_height=None,
    )

    assert (result.width, result.height) == (5, 7)
    assert result.quality is None
    assert result.content == original


def test_rejects_invalid_image(
    processor: ImageProcessor,
) -> None:
    """Проверяет отказ для данных, не являющихся изображением."""
    with pytest.raises(UnidentifiedImageError):
        processor.convert_to_jpeg(
            content=b"not-an-image",
            quality=None,
            target_width=None,
            target_height=None,
        )


def test_rejects_large_source_dimensions() -> None:
    """Проверяет предел размера исходного изображения."""
    source = BytesIO()
    Image.new("RGB", (5, 1), "blue").save(source, format="PNG")
    processor = ImageProcessor(
        max_image_dimension=4,
        max_image_pixels=100,
    )

    with pytest.raises(ValueError, match="Размер стороны"):
        processor.convert_to_jpeg(
            content=source.getvalue(),
            quality=None,
            target_width=None,
            target_height=None,
        )


def test_rejects_large_target_pixel_count() -> None:
    """Проверяет предел числа пикселей результата."""
    source = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(source, format="PNG")
    processor = ImageProcessor(
        max_image_dimension=10,
        max_image_pixels=20,
    )

    with pytest.raises(ValueError, match="Число пикселей"):
        processor.convert_to_jpeg(
            content=source.getvalue(),
            quality=None,
            target_width=5,
            target_height=5,
        )


def test_treats_decompression_warning_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Преобразует предупреждение Pillow в ошибку."""
    source = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(source, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 50)
    processor = ImageProcessor(
        max_image_dimension=100,
        max_image_pixels=1000,
    )

    with pytest.raises(Image.DecompressionBombWarning):
        processor.convert_to_jpeg(
            content=source.getvalue(),
            quality=None,
            target_width=None,
            target_height=None,
        )

