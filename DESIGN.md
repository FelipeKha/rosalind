
The Archive Ingestion Pipeline
```text
                     [Local Data Archives]
                     (Google, Spotify .zip)
                               │
                               ▼
                         [DropZone UI]
                      (Vite + React / TS)
                               │
                               ▼
                       [Tauri IPC Bridge]
                     (Validated Local Path)
                               │
                               ▼
                        [Command Router]
                         (Rust Backend)
                               │
                               ▼
                       [Stream Unzipper]
                     (In-Memory Buffers)
                               │
                               ▼
                       [Serde ETL Parser]
                     (Dogsheep-mapped Logic)
                               │
                               ▼
                     [Local SQLite Database]
```

The Discovery & Action Loops
```text
                     [Dashboard Interface]
                               │
     ┌─────────────────────────┴─────────────────────────┐
     ▼                                                   ▼
[Trigger Discovery Scan]                          [Request GDPR Erasure]
     │                                                   │
     ▼                                                   ▼
[Tauri IPC Bridge]                                [Tauri IPC Bridge]
     │                                                   │
     ▼                                                   ▼
[Paperweight Sidecar]                             [Query Local Registry]
 (Local IMAP Binary)                              (Datenanfragen Data)
     │                                                   │
     ▼                                                   ▼
[Extract Sender Headers]                          [Rust Mailer Component]
     │                                                   │
     ▼                                                   ▼
[Local SQLite Database]                          [Native OS Mail Client]
 (Populates Inventory)                           (Prefilled French Text)
```


## Architectural Subsystems Breakdown

### 1. Frontend Layer (Vite + React / TypeScript)
* Run entirely within the native operating system's Webview container (WebKit on macOS, WebView2 on Windows).
* Responsibilities include rendering the unified footprint analytics dashboard, handling file system drag-and-drop hooks for corporate archives, and executing full-text search filters.

### 2. Inter-Process Communication (IPC) Bridge
* Uses Tauri's strict, compile-time whitelisting to expose system capabilities to the frontend frontend using a secure message-passing architecture. 
* Prevents arbitrary code execution by scoping file access exclusively to user-selected paths.

### 3. Native Core Layer (Rust)
* **In-Memory Stream Unzipper:** Efficiently opens large user archives (e.g., multi-gigabyte Google Takeouts) and streams file buffers directly to memory without clogging the disk.
* **ETL Engine (Serde):** Translates raw, unstandardized JSON data arrays (modeled after open-source Dogsheep blueprints) into explicit structures optimized for transactional databases.
* **OS Intent Client:** Maps company profiles to generated text complying with French GDPR standards, initiating a secure local `mailto:` handler to hand off execution to the user's native email application.

### 4. Storage Layer (SQLite Embedded)
* Stored as a single flat file in the application's local user data folder. 
* **Datenanfragen Registry:** Pre-seeded via static build schemas tracking corporate Data Protection Officer (DPO) points of contact.
* **Ingested Service Data:** Dynamically structured relational tables grouping communication logs, location data, and tracking metrics extracted from verified third-party exports.



# Tech stack
## App Shell & Packaging Engine
Tauri v2

## Frontend Layer
- **Language:** TypeScript
- **UI Library:** React
- **Build Engine:** Vite
- **Core Component Foundations:** shadcn/ui + Tailwind CSS
- **Iconography:** Lucide React (Native companion library for shadcn primitives)
- **Asynchronous State & Cache Engine:** TanStack Query (React Query - Orchestrates asynchronous IPC bridge calls and cache invalidation)
- **Date Formatting:** date-fns
- **Data & Grid Engines:** 
  - TanStack Table (Headless sorting, filtering, and table state)
  - TanStack Virtual (DOM virtualization to prevent memory bloat on large datasets)
- **Geospatial & Mapping:**
  - MapLibre GL JS (WebGL/WebGPU accelerated engine for local data layers and real-time canvas rendering)
  - OpenFreeMap (Zero-tracking, API-keyless public OpenStreetMap vector tiles for high-precision street and shop basemaps)
- **Media Optimization:** 
  - Tauri Native Custom Asset Protocol (`asset://` URI engine for zero-clone, local-disk media streaming)
  - Interfaced with TanStack Virtual for smooth, un-cached 60fps photo-grid scrolling
- **Data Visualization:** Recharts
- **Form & Input Validation:** React Hook Form + Zod (Strict schema validation for settings and document generation)
- **Localization:** Native Intl APIs
- **i18n:** i18next + react-i18next
- **Testing:** 
  - **Component Level:** Vitest + React Testing Library + @tauri-apps/api/mocks
  - **E2E Fast Loop:** Playwright (Headless web-mode emulation)
  - **E2E Native Loop:** WebDriverIO + @wdio/tauri-service (Production binary automation)


IPC Bridge: Tauri Context
Backend: Rust
Storage: SQLite Database





# Third party tools
## Create list of digital footprint
### Paperweight 
Scan your inbox to map your digital footprint, then helps you take back control and delete your data. Local-first and open source. This is pretty close to what we are trying to do with Rosalind.  
[GitHub](https://github.com/wslyvh/paperweight) | [Website](https://www.paperweight.email/)

### Promnesia
Explore your browsing history in context: where you encountered it, in chat, on Twitter, on Reddit, or just in one of the text files on your computer.  
[GitHub](https://github.com/karlicoss/promnesia)

## Gather the data
### konnectors
Suite of connectors, scripts that import data from another web service.  
[GitHub](https://github.com/konnectors)

### Cozy Home
Platform that brings all your web services in the same private space, configure and runs cozy konnectors.  
[GitHub](https://github.com/linagora/cozy-home)

## Parse and organize personnal data
### google_takeout_parser
A library/CLI tool to parse data out of your Google Takeout (History, Activity, Youtube, Locations, etc...).  
[GitHub](https://github.com/purarue/google_takeout_parser)

### Human Programming Interface (HPI)
Package to unify, access and interact with personal data. Built on top of karlicoss HPI project.  
[GitHub](https://github.com/purarue/HPI)

### Dogsheep
Tools for personal analytics, powered by Datasette, propose a suite of tools to convert takeout data to sqlite.  
[GitHub](https://github.com/dogsheep)

### Datasette
Tool for exploring and publishing data. It helps people take data of any shape, analyze and explore it, and publish it as an interactive website and accompanying API.  
[GitHub](https://github.com/simonw/datasette) | [Website](https://datasette.io/)

### Datenanfragen.de
Request generator to get access to, delete, correct my data, and stop receiving direct marketing. They have a database of contact information of many companies for privacy-related requests.  
[GitHub](https://github.com/datenanfragen) | [Website](https://www.datarequests.org/)

## Analyse T&C to understand what could have been done of my data
### Open Terms Archive
publicly records every version of the terms of digital services to enable democratic oversight.  
[GitHub](https://github.com/OpenTermsArchive) | [Website](https://opentermsarchive.org/en/)

### Terms of Service; Didn't Read” (ToS;DR)
Get informed instantly about websites' terms & privacy policies, with ratings and summaries.  
[GitHub](https://github.com/tosdr) | [Website](https://tosdr.org/en)

## Send delete requests
### auto-identity-remove
Automated data broker opt-out runner for macOS, Linux, and Windows. Removes your personal information from 500+ people-search sites and data broker databases on a monthly schedule.  
[GitHub](https://github.com/stephenlthorn/auto-identity-remove)

### Big Ass Data Broker Opt-Out List (BADBOOL)
US centric data broker opt our list.  
[GitHub](https://github.com/yaelwrites/big-ass-data-broker-opt-out-list)

### opt-out-manual-2026
2026 DIY Opt-Out Manual For Removal From Over 400 Sites. The guide shows difficulty rating, an estimate of how long it will take, and the exact instructions to opt-out per site in an easy to read user manual.  
[GitHub](https://github.com/thumpersecure/opt-out-manual-2026)





authn and authz:

- Several users may want to use the app on the same machine, they should be able to login with their own profile

- All the data store in our db should be encrypted - we should make it as safe as possible, if the machine is lost the data should not be usable

- In the future, we may want third parties to access some of our data, in a controlled way - e.g. I want to authorize my doctor to access my latest blood analysis results, but not my tax returns, while my accountant can access my tax returns but not my blood analysis 


Open questions:
- How can I get my tracker data stored in the cloud?