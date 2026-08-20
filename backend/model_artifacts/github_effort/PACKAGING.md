# GitHub Task Duration runtime artifacts

Bundle this directory at `<resource-root>/model_artifacts/github_effort`, or set
`SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR` to its absolute packaged location.
`SMARTDESK_GITHUB_RESOURCE_ROOT` may instead point at the packaged backend
resource root. Resolution does not depend on the process working directory.

## Required files

- `model_low.txt` — P10 estimate
- `model_typical.txt` — P50/main Initial Estimate
- `model_high.txt` — P90 estimate
- `manifest.json` — ordered 56-feature schema and training metadata
- `preprocessing_manifest.json` — runtime schema, rules, and SHA-256 inventory
- `tfidf_vectorizer.pkl`
- `svd_reducer.pkl`
- `inference_fallbacks.json`
- `repo_stats.json`
- `repo_label_stats.json`
- `label_categories.json`

The three LightGBM text files must remain LF-only. Ship the integrity manifest
with the exact artifacts it hashes; do not regenerate hashes unless an artifact
is intentionally replaced. Runtime loading validates hashes before unpickling.

Inference requires no training dataset and performs no retraining. Install the
full backend requirements, including `requirements-prediction.txt`, and bundle
the `github_data_collection` Python package rather than relying on its editable
development path.

