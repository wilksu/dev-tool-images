# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through the repository's GitHub
Security Advisory interface. Do not open a public issue for an unpatched
vulnerability or include credentials, private registry references, or other
secrets in a report.

Include the affected image name and digest, the source revision when known, a
minimal reproduction, and the expected impact. Maintainers will acknowledge the
report, determine affected release digests, and coordinate a fixed release.

## Supported releases

Tool images are immutable. A fixed image is published under a new semantic
version and digest; published manifests are never replaced in place. Consumers
are responsible for updating their own digest locks after validating a fixed
candidate.
