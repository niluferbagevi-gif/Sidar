# Modular `.env.example` fragments

The root `.env.example` file remains the copy-paste friendly canonical template.
These numbered fragments split the same content into smaller, reviewable sections for
new contributors and for tooling that wants to compose a minimal env file.

To reconstruct the canonical template from fragments:

```bash
cat .env.example.d/[0-9][0-9]-*.env > .env.example
```

To create a local env from fragments without editing the large template directly:

```bash
cat .env.example.d/[0-9][0-9]-*.env > .env
```

Keep fragments synchronized with `.env.example`; the unit tests compare the normalized
concatenation with the root template.
