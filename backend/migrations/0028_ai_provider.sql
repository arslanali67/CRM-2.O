-- AI provider choice (PROJECT.md v1.49): NULL = automatic (OpenRouter when its key is present, else Gemini).
-- Model ids from OpenRouter look like 'nvidia/nemotron-3-ultra-550b-a55b:free', so the pattern is widened.
ALTER TABLE app_settings
    ADD COLUMN ai_provider text CHECK (ai_provider IN ('openrouter', 'gemini')),
    DROP CONSTRAINT app_settings_ai_model_check,
    ADD CONSTRAINT app_settings_ai_model_check CHECK (ai_model ~ '^[A-Za-z0-9][A-Za-z0-9._:/\-]{1,100}$');
