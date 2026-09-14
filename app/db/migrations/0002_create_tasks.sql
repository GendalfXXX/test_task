CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',

    source_path TEXT,
    original_filename TEXT,
    source_image_id UUID REFERENCES images(id) ON DELETE RESTRICT,
    result_image_id UUID REFERENCES images(id) ON DELETE RESTRICT,

    quality SMALLINT,
    target_width INTEGER,
    target_height INTEGER,

    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    CONSTRAINT tasks_type_allowed
        CHECK (task_type IN ('upload', 'resize')),
    CONSTRAINT tasks_status_allowed
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    CONSTRAINT tasks_source_path_not_blank
        CHECK (source_path IS NULL OR BTRIM(source_path) <> ''),
    CONSTRAINT tasks_original_filename_not_blank
        CHECK (
            original_filename IS NULL
            OR BTRIM(original_filename) <> ''
        ),
    CONSTRAINT tasks_quality_range
        CHECK (quality IS NULL OR quality BETWEEN 1 AND 100),
    CONSTRAINT tasks_target_width_positive
        CHECK (target_width IS NULL OR target_width > 0),
    CONSTRAINT tasks_target_height_positive
        CHECK (target_height IS NULL OR target_height > 0),
    CONSTRAINT tasks_source_matches_type
        CHECK (
            (
                task_type = 'upload'
                AND source_path IS NOT NULL
                AND original_filename IS NOT NULL
                AND source_image_id IS NULL
            )
            OR
            (
                task_type = 'resize'
                AND source_path IS NULL
                AND original_filename IS NULL
                AND source_image_id IS NOT NULL
                AND target_width IS NOT NULL
                AND target_height IS NOT NULL
                AND quality IS NULL
            )
        ),
    CONSTRAINT tasks_state_is_consistent
        CHECK (
            (
                status = 'pending'
                AND started_at IS NULL
                AND finished_at IS NULL
                AND result_image_id IS NULL
                AND error_message IS NULL
            )
            OR
            (
                status = 'processing'
                AND started_at IS NOT NULL
                AND finished_at IS NULL
                AND result_image_id IS NULL
                AND error_message IS NULL
            )
            OR
            (
                status = 'completed'
                AND started_at IS NOT NULL
                AND finished_at IS NOT NULL
                AND result_image_id IS NOT NULL
                AND error_message IS NULL
            )
            OR
            (
                status = 'failed'
                AND started_at IS NOT NULL
                AND finished_at IS NOT NULL
                AND result_image_id IS NULL
                AND error_message IS NOT NULL
                AND BTRIM(error_message) <> ''
            )
        ),
    CONSTRAINT tasks_timestamps_ordered
        CHECK (
            (started_at IS NULL OR started_at >= created_at)
            AND (finished_at IS NULL OR finished_at >= started_at)
        )
);

CREATE TRIGGER tasks_set_updated_at
BEFORE UPDATE ON tasks
FOR EACH ROW
EXECUTE FUNCTION set_image_service_updated_at();

CREATE INDEX tasks_pending_created_at_idx
    ON tasks (created_at)
    WHERE status = 'pending';

CREATE INDEX tasks_source_image_id_idx
    ON tasks (source_image_id)
    WHERE source_image_id IS NOT NULL;

CREATE INDEX tasks_result_image_id_idx
    ON tasks (result_image_id)
    WHERE result_image_id IS NOT NULL;
