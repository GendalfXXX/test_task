CREATE FUNCTION set_image_service_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TABLE images (
    id UUID PRIMARY KEY,
    content BYTEA NOT NULL,
    original_filename TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'image/jpeg',
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    size_bytes BIGINT NOT NULL,
    quality SMALLINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT images_original_filename_not_blank
        CHECK (BTRIM(original_filename) <> ''),
    CONSTRAINT images_jpeg_only
        CHECK (media_type = 'image/jpeg'),
    CONSTRAINT images_width_positive
        CHECK (width > 0),
    CONSTRAINT images_height_positive
        CHECK (height > 0),
    CONSTRAINT images_size_positive
        CHECK (size_bytes > 0),
    CONSTRAINT images_quality_range
        CHECK (quality IS NULL OR quality BETWEEN 1 AND 100),
    CONSTRAINT images_content_size_matches
        CHECK (OCTET_LENGTH(content) = size_bytes)
);

CREATE TRIGGER images_set_updated_at
BEFORE UPDATE ON images
FOR EACH ROW
EXECUTE FUNCTION set_image_service_updated_at();

CREATE INDEX images_created_at_idx
    ON images (created_at DESC);
