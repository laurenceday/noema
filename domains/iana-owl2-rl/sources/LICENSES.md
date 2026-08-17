# Source licences and provenance

`iana-application-2026-08-14.csv` and
`iana-structured-syntax-suffix-2026-06-25.csv` are byte-preserved downloads of
the official IANA protocol registries named by their companion JSON slices.
The CSV files and generated slices are available under the Creative Commons
CC0 1.0 dedication. The IANA/IETF statement is at
<https://www.iana.org/help/licensing-terms>.

`extract_iana_slices.py` verifies the two upstream digests and reconstructs the
JSON views without a network request. The generated files record their source
paths, official URLs, registry dates, retrieval date, selectors, and parent
SHA-256 digests.

`rfc6838.txt` and `rfc6839.txt` are byte-preserved RFC Editor text editions.
Their original copyright and legal notices remain inside each file. They are
redistributed under the IETF Trust Legal Provisions in force for these 2013
RFCs, recorded here as `LicenseRef-IETF-TLP-4.0`.

`rfc8259.txt` is the byte-preserved RFC Editor text edition of RFC 8259. Its
original copyright and legal notices remain inside the file. It is
redistributed under the IETF Trust Legal Provisions in force for this 2017
RFC, recorded here as `LicenseRef-IETF-TLP-5.0`.

`rfc-locators.json` contains local provenance descriptions and links. Its
locator text is not used as evidence for an RFC claim. The file and the local
formal artefacts are licensed under Apache-2.0.
