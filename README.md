# Image Unmasking

Flask web app using Sightengine's AI-generated image detection API.

## Deploy on Render

1. Upload this folder to GitHub. Never upload API keys, `.env`, or `truthlens.db`.
2. In Render, choose **New → Blueprint**, then select the repository.
3. Render reads `render.yaml`. Enter the private `SIGHTENGINE_API_USER` and `SIGHTENGINE_API_SECRET` values when prompted.
4. Apply the deployment. Render gives you a public HTTPS URL.

## Accounts

SQLite is used locally for accounts and history. Before using public accounts long-term, move to a managed PostgreSQL database because normal Render service storage is temporary.
