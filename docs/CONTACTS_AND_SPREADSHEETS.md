# Contacts and spreadsheets

OpenShare 0.2.36 adds two owner-scoped productivity features to the existing file library: a
contact manager and read-only spreadsheet previews. Both use the same OpenID Connect identity,
SQLite metadata store, responsive React interface, and share/download controls as the rest of
OpenShare.

## Contact manager

Open **Contacts** from the primary navigation. Contacts are private to the authenticated OpenShare
owner and are never included in public folder or media shares.

Each contact can store:

- display, given, and family names;
- company and role;
- multiple email addresses, phone numbers, and postal addresses;
- birthday, notes, and membership in multiple color-coded groups;
- an optional OpenChat username and 8-digit friend code.

The contact list searches names, companies, contact methods, notes, and OpenChat identity fields.
Group filters can be combined with search. Deleting a group preserves its contacts.

### Import and export

The import action accepts vCard (`.vcf` or `.vcard`) and CSV files. CSV recognizes common column
names such as `name`, `first_name`, `last_name`, `email`, `phone`, `company`, `title`, and the
OpenShare-specific `openchat_username` and `openchat_friend_code` fields. Multiple email addresses,
phone numbers, or addresses can be separated by commas, semicolons, or lines.

Export produces a standards-oriented vCard 4.0 file containing all contacts. OpenChat linkage is
preserved with `X-OPENCHAT-USERNAME` and `X-OPENCHAT-FRIEND-CODE` extension properties.

### OpenChat integration

Set the optional companion URL in OpenShare:

```dotenv
OPENCHAT_PUBLIC_URL=https://chat.example.com
```

A linked contact then offers **Copy friend code** and **Open OpenChat** actions. OpenShare puts only
the username or friend code in the OpenChat URL. OpenChat opens its Friends screen with that value
prefilled, and the user must explicitly submit the request. Names, notes, addresses, phone numbers,
and email addresses are not transferred.

## Spreadsheet management and viewer

Spreadsheets participate in the normal OpenShare workflow: upload to Unsorted or a selected folder,
move in bulk, search, download, delete, and create a recorded public media share.

The viewer supports:

| Format | Extensions | Preview behavior |
|---|---|---|
| Excel Open XML | `.xlsx`, `.xlsm` | Multi-sheet, calculated cell values |
| Excel binary and legacy | `.xlsb`, `.xls` | Multi-sheet, calculated cell values |
| OpenDocument | `.ods` | Multi-sheet, calculated cell values |
| Delimited text | `.csv`, `.tsv` | Single-sheet preview with delimiter detection |

The viewer is intentionally read-only. It provides sheet tabs, sticky row and column headings,
horizontal and vertical table navigation, and pages of up to 200 rows. It displays at most 100
columns per page while reporting the workbook's full detected dimensions. The original file is
always available through the viewer's Open original and Download actions.

Binary workbook parsing runs server-side through `python-calamine`; uploaded macros and formulas
are not executed. The viewer exposes stored or calculated cell values rather than an editable
office runtime.

## API summary

Authenticated contact operations:

- `GET/POST /api/contacts`
- `PUT/DELETE /api/contacts/{contact_id}`
- `GET/POST /api/contact-groups`
- `DELETE /api/contact-groups/{group_id}`
- `POST /api/contacts/import`
- `GET /api/contacts/export.vcf`

Spreadsheet viewer operations:

- `GET /ss/{media_id}` renders the common React media viewer.
- `GET /api/spreadsheets/{media_id}?sheet=...&offset=...&limit=...` returns bounded preview data.
- `GET /raw/{media_id}` returns the unmodified source file.

State-changing browser requests remain protected by OpenShare's trusted-origin boundary. Contact
queries and writes always include the authenticated owner identity.

## Verification

The backend harness covers contact CRUD, ownership isolation, search, groups, validation,
vCard import/export, spreadsheet classification, CSV preview bounds, workbook sheet selection, and
preview paging. The React suite covers contact search, OpenChat actions, editor validation, and the
multi-sheet viewer. `make verify` runs these tests alongside coverage, builds, linting, deployment
checks, and dependency auditing.
