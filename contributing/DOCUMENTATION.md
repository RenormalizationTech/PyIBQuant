# Maintaining and publishing the documentation

[User documentation](../docs/README.md) · [Contributing](../CONTRIBUTING.md)

The documentation is prepared for a GitHub Pages website built with MkDocs and
the Material theme. Desktop navigation is a persistent vertical sidebar on the
left, with page headings on the right; smaller screens use a menu drawer.
Markdown in `docs/` is the source of truth for both GitHub readers and the website.
The generated `site/` directory is ignored by Git and should not be committed.

## Preview locally

From the repository root, with a Python 3.11+ virtual environment active:

```sh
python -m pip install -e '.[docs]'
python -m mkdocs serve
```

Open the URL printed by MkDocs. The configured project URL includes `/PyIBQuant/`,
so the preview also uses that prefix (normally
`http://127.0.0.1:8000/PyIBQuant/`). Saving a documentation file reloads the preview.
Ctrl+C stops the server. No IBKR SDK, market connection or private account data is
needed to build documentation.

For a production build without running a server:

```sh
python -m mkdocs build --strict
```

This creates `site/`. Navigation mistakes, missing local targets and invalid
heading anchors fail the strict build. External URLs are not checked for network
availability. The pinned MkDocs and Material versions live in the `docs` optional dependency
in `pyproject.toml`; review and build locally when updating it.

## GitHub Actions behavior

The **Documentation** workflow in `.github/workflows/docs.yml`:

1. Builds on documentation/configuration pull requests and matching pushes to `main`.
2. Installs only the package and documentation extra, then runs the strict build.
3. Uploads the generated site as a `github-pages` artifact for inspection.
4. Deploys after a successful build on pushes to `main` that change these paths,
   or on a manual run on `main` with **publish** checked.

Pull requests never publish. A manual run with **publish** unchecked only builds.
Pushes that change only files outside `docs/`, `mkdocs.yml`, `pyproject.toml` and
the workflow do not run it; use a manual run with **publish** to republish then. Pull request jobs have read-only repository permissions; only
the deployment job receives Pages write and OIDC permissions. No personal access
token or `gh-pages` branch is needed. These jobs build the Markdown site; they do
not run the code examples or broker integration checks.

## Enable GitHub Pages when ready

Once these files are committed and pushed to GitHub:

1. In the repository, open **Settings → Pages → Build and deployment**.
2. Select **GitHub Actions** as the source.
3. In **Settings → Environments → github-pages**, restrict deployments to `main`
   and configure any desired reviewer requirements.
4. Open **Actions → Documentation → Run workflow**, choose `main`, check
   **publish**, and run it.
5. After the deployment succeeds, use the URL shown by the deployment job.

The configured target is
[the PyIBQuant Pages address](https://renormalizationtech.github.io/PyIBQuant/).
It is the intended address, not a claim that the site is already published.
Nothing in this preparation changes remote repository settings or deploys a site.

Automatic publication from `main` is enabled: the deploy job's `if` allows push
events on `main` as well as the explicit manual publish case. Keep the branch
restriction and the `github-pages` environment controls when changing it.

## Theme and layout

`mkdocs.yml` selects the Material theme. `navigation.sections` groups the API
reference in the left sidebar, and `navigation.expand` keeps its pages visible.
Horizontal navigation tabs are intentionally disabled. The page table of contents
remains separate on the right on wide screens. Search and the mobile menu remain
in the compact header.

Small typography, header and sidebar adjustments live in
`docs/stylesheets/extra.css`. System fonts avoid external font downloads. To change
which pages appear in the sidebar, edit `nav` in `mkdocs.yml`; no Markdown content
needs to be rewritten. After changing themes or dependencies, reinstall `.[docs]`
and restart the preview server.

## Editing conventions

- Keep user guides under `docs/` and add them to `nav` in `mkdocs.yml`.
  Keep contributor/build/publication instructions in `contributing/`, outside the website.
- Start each page with one descriptive level-one heading. Use level-two/three
  headings to provide a useful page table of contents.
- Link documentation pages using relative Markdown paths, such as
  `[Quick start](../docs/QUICKSTART.md)`. MkDocs converts these to website URLs while the
  links remain useful when reading source files on GitHub.
- Link repository files outside `docs/` to their full GitHub URLs, including the
  correct `blob/main/` or `tree/main/` path. Relative `../examples/` links escape
  the documentation source tree and will not point to published example files.
- Keep `.md` filenames and heading anchors stable when possible. Update incoming
  links if changing them, then run the strict build.
- Use fenced code blocks with `python`, `sh` or `text` language labels. Signature
  notation containing a bare `*` belongs in `text` blocks, not runnable Python.
- State prerequisites, reused files, argument units and expected results for
  examples. Label synthetic fixtures and distinguish offline, connected data,
  observation and execution examples.
- Keep generated charts, caches, journals, credentials and account reports outside
  `docs/`; MkDocs publishes files placed in that directory. Use synthetic or
  intentionally public assets for illustrations.
- Check the [offline walkthrough](../docs/QUICKSTART.md) after changing its documented API.
  The website build validates Markdown links, not Python behavior.

For a repository rename, organization change or custom domain, update `site_url`,
`repo_url`, and `edit_uri` in `mkdocs.yml` as appropriate, plus repository links in
the guides. The project path in `site_url` matters for canonical links and local
preview paths. Keep internal site links relative so project-path hosting works.

Configuration references:
[MkDocs configuration](https://www.mkdocs.org/user-guide/configuration/) and
[GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

Theme reference: [Material navigation settings](https://squidfunk.github.io/mkdocs-material/setup/setting-up-navigation/).
