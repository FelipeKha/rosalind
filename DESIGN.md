# Tech stack
## App Shell & Packaging Engine
Tauri v2

## Frontend Layer
- **Language:** Rust
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

## Backend
- **Language:** Rust
- **Database driver:** r2d2 + r2d2_sqlite
- **Key Derivation Function:** argon2

## Application Shell & Inter-Process Communication (IPC) Bridge
Framework: Tauri v2

## Storage
Framework: SQLCipher

# Authentication and encryption:
We use the Envelope Encryption for authentication (authn) and data security.
Data Encryption Key (DEK): key used to encrypt data itself 
Key Encryption Key (KEK): key used to encrypt (or wrap) the DEK. The process of encrypting a key with another key is known as envelope encryption

### Key rotation:
KEK:  
- Cost: low (no db write)
- Strategy: 
  - User passphrase: no mandatory calendar expiration
  - Transparent refresh: opportunistic salt and Argon2id parameter updates executed automatically in Rust memory during successful login events

DEK:
- Cost: high (full db rewrite)
- Strategy: event driven rotation, upon suspected incident, backup (each backup should have its own DEK), major migration

KEK salt and DEK are saved in the same directory as the user's database in `profile_header.json`.
```text
~/.myapp/profiles/alice/
├── profile_header.json   <-- The Key Envelope (Contains Wrapped DEKs & KDF Parameters)
└── vault.db              <-- SQLCipher Database (Payload encrypted by raw DEK)
```


### Authentication Model
Streamlined Single-Factor Master Passphrase (Argon2id + SQLCipher) with optional OS-level Biometric Quick-Unlock (Touch ID / Windows Hello via tauri-plugin-biometric). No cloud or TOTP MFA required.

Master Passphrase + Argon2id (Mandatory Core):

    This is the single mathematical key that encrypts and decrypts the database.

    As long as the user picks a decent passphrase, SQLCipher is uncrackable offline.

Biometric / Hardware Quick-Unlock (Optional UX Convenience):

    Do not use Touch ID / Windows Hello as a forced second factor. Use it as an optional convenience token.

    The user enters their long passphrase once when setting up the app. The derived key is stored securely in the OS Secure Enclave / TPM chip.

    On day-to-day app launches or after a 5-minute idle timeout, the user simply taps Touch ID or scans Windows Hello to unlock the vault instantly, without typing their 20-character passphrase every time.


### Key Envelope & Account Recovery
- **Key Architecture:** Master Encryption Key (MEK) Envelope pattern.
  - SQLCipher is encrypted using a random 256-bit MEK.
  - MEK is dual-wrapped using AES-256-GCM and stored in `profile_header.json`:
    - **Slot 1 (Passphrase):** Wrapped using `Argon2id(Passphrase, Salt)`.
    - **Slot 2 (Recovery):** Wrapped using `Argon2id(BIP-39 Seed Phrase, Salt)`.
- **Passphrase Reset:** Decrypting Slot 2 via the 24-word Recovery Kit reveals the MEK, enabling zero-re-encryption passphrase updates.
- **Data Loss Boundary:** Zero-knowledge model. Loss of both Passphrase and Recovery Kit renders the database irrecoverable. Users retain the option to delete the profile container and re-ingest raw local source files (`.zip`/`.json`).


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


References:
https://docs.cloud.google.com/kms/docs/envelope-encryption
