# ERP requirements and design package

Detailed, source-grounded LaTeX documents for **both** repositories:

- Backend: `ERP_System_backend`, baseline `6e10c54`.
- Frontend: sibling `ERP_System`, baseline `6cc6859`.
- Stakeholder authority: [SEN4121 Summer 2026 brief](../Large_System_Environment_SET_A_Summer%202026.pdf).

## Read the deliverables

| Deliverable | PDF | Editable source |
|---|---|---|
| Software Requirements Specification | [srs.pdf](output/srs.pdf) | [srs.tex](srs.tex) |
| Software Design Document / technical report | [sdd.pdf](output/sdd.pdf) | [sdd.tex](sdd.tex) |
| UML suite: 22 diagrams | Embedded in the documents | [PlantUML sources](diagrams/) |
| Zoomable diagrams | [SVG and PNG renders](diagrams/rendered/) | Shared [theme](diagrams/theme.puml) |

The complete SRS is **33 pages** and the SDD **57 pages**, including detailed
appendices and diagram sheets. The [artifact verification record](output/validation.json)
contains page-budget checks, source counts and SHA-256 hashes for the verified PDFs.

The SRS includes individually identified functional/nonfunctional requirements,
acceptance conditions, ten use cases, frontend coverage, test traceability,
assumptions, risks and submission checklists. The SDD includes frontend composition,
authentication, four service domains, calculations, data normalization rationale,
transaction boundaries, deployment, operations and source-generated inventories of
**97 service-local routes and 42 persisted models**.

### Assignment page limit

The brief limits **SRS plus technical report together** to 20 pages, excluding
appendices and diagrams. This package budgets:

- SRS: 3 front-matter pages + 6 main narrative pages = 9 counted pages.
- SDD: 3 front-matter pages + 8 main narrative pages = 11 counted pages.
- **Combined counted total: 20 pages**, including covers, document control and contents.
- Detailed catalogues, tables, UML and operational material are explicitly labeled
  appendices. The complete PDFs are therefore longer than 20 physical pages.

This is not a claim that each document independently gets a 20-page allowance.
Recheck pagination after editing content or changing the typesetter/fonts.

### Important accuracy qualifications

- Implemented, partial and target requirements are distinguished; a test file's
  existence is not a successful test-run result.
- The frontend supports student academics/payments and staff self-service. Instructor,
  finance administration, HR administration and settings screens are largely placeholders;
  the overview is not an analytics dashboard.
- Historical local load latency **fails** the stated p95 target. The short local
  PITR drill does not prove full ERP production recovery.
- MTN adapter code is not evidence of a credentialed sandbox run. Payroll rate
  attestation is not statutory certification.
- Production Compose inheritance, callback ingress, artifact publication and
  off-host backups are documented release gates, not silently treated as complete.
- This is AI-assisted documentation. Names, signatures, team contributions, legal
  approvals and application test results have not been fabricated.

## Build locally on Windows

Tools used: **Java 21**, **PlantUML 1.2025.4**, **Tectonic 0.15.0**, and Python 3.10+
for dependency-free static inventory generation. No application dependencies or
running ERP stack are needed for the documentation build.

Obtain tools from their official distributions:

- [PlantUML releases](https://github.com/plantuml/plantuml/releases/tag/v1.2025.4)
  or Maven artifact `net.sourceforge.plantuml:plantuml:1.2025.4`.
- [Tectonic 0.15.0](https://github.com/tectonic-typesetting/tectonic/releases/tag/tectonic%400.15.0),
  Windows x86-64 MSVC archive.

Keep tool executables outside the source tree. From this directory:

```powershell
.\build.ps1 `
  -PlantUmlJar "C:\tools\plantuml-1.2025.4.jar" `
  -Tectonic "C:\tools\tectonic.exe" `
  -Python "C:\path\to\python.exe"
```

`-Java` can specify an executable if Java is not on PATH. `PLANTUML_JAR` is accepted
as an environment-variable default. The paths above are examples, not installation
commands. The script does not download or install tools.

The build:

1. Reads Python syntax trees and regenerates ignored `generated/endpoints.tex` and
   `generated/models.tex`; it does not import services or inspect secrets.
2. Locally renders every diagram to PNG and SVG using the bundled Smetana layout
   engine; no external Graphviz installation or public rendering server is required.
   Each render replaces its previous output; missing or empty output fails the build
   rather than silently reusing a stale diagram.
3. Compiles both PDFs and rejects compiler errors, unresolved references and overfull boxes.

Tectonic may download its typesetting bundle on first use. Diagram and document
content remain local. Generated PDFs and diagram renders are deliverables; LaTeX
intermediates, generated source inventories and Python cache files are ignored.
Retain source diagrams with their output so reviewers can reproduce and modify them.

The narrative and tables use A4. Diagram appendices use **A3/A2 engineering sheets**
to keep dense UML readable, with SVG originals for unrestricted zoom. For printing,
use original sheet size where possible rather than shrinking every diagram to A4.

## Diagram index

| ID | View |
|---|---|
| 01 | System context |
| 02 | Actors and use cases |
| 03 | Runtime components and service ownership |
| 04 | React frontend composition and data flow |
| 05a | Full system class diagram: every object, attribute and relation across all four bounded contexts |
| 05 | Payment protocol / ORM / payroll class collaboration |
| 06 | Identity ERD |
| 07 | Academic ERD |
| 08 | Finance and Marketing ERD |
| 09 | HR ERD |
| 10 | Authentication, delegation and refresh sequence |
| 11 | Asynchronous enrollment-to-invoice sequence |
| 12 | Payment initiation and settlement sequence |
| 13 | Grade appeal state machine |
| 14 | Payroll computation and approval activity |
| 15 | Leave decision and notification sequence |
| 16 | Compose containers, network, volumes and production prerequisites |
| 17 | Target full-system recovery activity |
| 18 | Conceptual scaling strategy |
| 19 | Browser session state machine |
| 20 | Exam conflict-check activity |
| 21 | Asset movement and stock-invariant activity |

## Review before submission

Attach actual application test/coverage reports, query plans, load and recovery
artifacts, OpenAPI exports, issue-board evidence and a reproducible live demo.
The team must complete the brief's signed contribution/integrity statements and
disclose AI assistance. These documents do not modify missing product features
or certify the system as production-ready.
