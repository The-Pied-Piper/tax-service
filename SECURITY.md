# Security policy

## Supported versions

service-template has no releases yet. Security fixes are made on the `main` branch.

## Reporting a vulnerability

Please report security problems privately. Do not open a public issue or pull request for them.

Use GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**. Only the maintainers can see the report.

Please include:

- what you found and which part of the template it affects,
- steps or a small example that reproduces it,
- the commit you tested.

## What to expect

We will acknowledge a report as soon as we can, work with you to confirm and fix the problem, and credit you in the fix if you wish. Please give us a reasonable chance to release a fix before you disclose the problem publicly.

## What counts as a security issue

Examples: unsafe handling of an OpenAPI spec by the generator, generated code or template files that introduce a vulnerability into services, and insecure defaults in the shipped Dockerfile or compose file.

Bugs in a service built from the template, and vulnerabilities in a service's own code, belong to that service's repository.
