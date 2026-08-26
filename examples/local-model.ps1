# Example configuration for an OpenAI-compatible server running locally.
$env:AI_COMMIT_API_KEY = "local-development"
$env:AI_COMMIT_BASE_URL = "http://localhost:1234/v1"
$env:AI_COMMIT_MODEL = "local-model"

commitgen generate --style conventional
