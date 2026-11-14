# Security policy

## Supported versions

Production runs the latest release (`v1`, `v2`, and so on, listed under Releases). Security fixes are made on the `main` branch and reach production in a new release.

## Reporting a vulnerability

Please report security problems privately. Do not open a public issue or pull request for them.

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Only the maintainers can see the report.

Please include:

- what you found and which part of the service it affects,
- steps or a small example that reproduces it,
- the commit or release you tested.

## What to expect

We will acknowledge a report as soon as we can, work with you to confirm and fix the problem, and credit you in the fix if you wish. Please give us a reasonable chance to release a fix before you disclose the problem publicly.

## What counts as a security issue

Examples: a request that crashes the API or makes it use excessive resources, unsafe handling of input, a way to read data or run code you should not, a weakness in the Docker image, or in the release and deployment workflows in `.github/workflows`.

A wrong tax figure is not a security issue. Please open a normal issue for it, in [tax-engine](https://github.com/The-Pied-Piper/tax-engine) if the figure comes from the calculation, or here if the API returns something different from the engine. Vulnerabilities in tax-engine or in third-party libraries belong to those projects (for tax-engine, report them there).
