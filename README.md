# Image Unmasking

Flask web app using Sightengine's AI-generated image detection API.

## Deploy on Render

1. Upload this folder to GitHub. Never upload API keys, `.env`, or `truthlens.db`.
2. In Render, choose **New → Blueprint**, then select the repository.
3. Render reads `render.yaml`. Enter the private `SIGHTENGINE_API_USER` and `SIGHTENGINE_API_SECRET` values when prompted.
4. Apply the deployment. Render gives you a public HTTPS URL.

## Accounts

SQLite is used locally for accounts and history. Before using public accounts long-term, move to a managed PostgreSQL database because normal Render service storage is temporary.


## Google Search

After deploying the app to a public HTTPS URL:

1. Add the live site as a property in [Google Search Console](https://search.google.com/search-console/) and verify that you own it.
2. Submit `https://YOUR-LIVE-DOMAIN/sitemap.xml` in Search Console's **Sitemaps** section.
3. Use **URL Inspection** on the home page and request indexing.

The public home page includes a search title and description. The app also serves `/robots.txt` and a sitemap containing its public home page. Google decides whether and when to index a site; submission does not guarantee that it will appear for a particular search.
