# Zoho CRM - Bulk Deal Closure

Two Deluge functions that take every Deal in a CRM filter (Custom View) and:

1. set **Stage** to the configured closing stage,
2. add the tag **AutoClosed**,
3. attach a **Note** explaining the closure.

| File | Use it when | Needs a Connection |
|---|---|---|
| `bulk_close_deals.dg` | Up to a few hundred Deals. Uses the built-in `zoho.crm.*` tasks, nothing to set up. | No |
| `bulk_close_deals_api.dg` | Hundreds to a few thousand Deals. Uses the v8 REST API in batches of 100, so ~20x fewer integration calls. | Yes |

## Target stage

`TARGET_STAGE` is set to **Closed Lost**, matching the picklist spelling on the
Deals layout.

Deals already on a closed stage are skipped, and that list includes
**Closed Won**. So a won deal sitting inside the filter is left alone rather
than flipped to lost, which would rewrite closed revenue and forecast history.
If you really do want won deals flipped, remove that one line from
`SKIP_STAGES`.

The full picklist is Qualification, Presentation & Demo, Proposal/Price Quote,
Negotiation/Review, Closed Won, Closed Lost, Closed Lost to Competition.

## Values already filled in for this org

| Setting | Value |
|---|---|
| Custom View (filter) | `833326000092565978` |
| Target stage | `Closed Lost` |
| Records per run | `2` (pilot limit, raise after verifying) |
| Data centre / API domain | `https://www.zohoapis.in` |
| Module | `Deals` (shown as Potentials in the URL) |

## Setup

1. **Share the filter.** The view must be visible to the user the function runs
   as, otherwise the fetch returns `INVALID_DATA` on `cvid`. In CRM open the
   view, then *Edit > Share this view > All users* (or at least the admin who
   owns the function).
2. **Create the tag** `AutoClosed` once under *Setup > Customization > Tags*,
   open it, and copy its ID into `TAG_ID` in `bulk_close_deals.dg`. The API
   version creates the tag on its own, so this step is only for the simple
   version.
3. **Paste the function** into *Setup > Developer Space > Functions >
   New Function*, category **Standalone**, and save.
4. For `bulk_close_deals_api.dg` only, create the connection described in the
   file header (`Zoho OAuth`, link name `zcrm_conn`, scopes
   `ZohoCRM.modules.ALL`, `ZohoCRM.settings.tags.ALL`,
   `ZohoCRM.settings.custom_views.READ`).

## Running it

`MAX_RECORDS_PER_RUN` ships at **2**. It counts Deals that will actually be
changed, not rows read, so a run cannot touch more than two records even if the
first hundred rows in the view turn out to be skippable.

1. Leave `DRY_RUN = true` and hit **Save & Execute**. Read the execution log.
   It names the two Deals it would touch and changes nothing.
2. Set `DRY_RUN = false` and run again. Two Deals move to Closed Lost.
3. Open those two in CRM. Check the stage, the `AutoClosed` tag, and the note
   in the Notes related list.
4. Happy? Raise `MAX_RECORDS_PER_RUN` and run for real.

Both functions are safe to re-run. A Deal already on a closed stage, or already
carrying the `AutoClosed` tag, is skipped, so repeated runs work through the
filter rather than reprocessing the same records.

## For very large filters

`MAX_RECORDS_PER_RUN` caps one execution so you do not hit Deluge's per-run
integration-call limit. If the filter excludes closed Deals, each run shrinks
the filter, so the clean way to work through thousands of records is to attach
the function to a **scheduled function** (*Setup > Automation > Schedules*)
running every 15 minutes until the filter is empty.

Note that the fetch itself is capped at 2000 records by the API
(`MAX_PAGES x PER_PAGE`), which is why the schedule approach matters.

## Things that can make an update fail

The summary mail reports these per Deal, it does not stop the run.

- **Validation rules** on Deals, for example a mandatory loss-reason field
  when moving to Closed Lost. If the layout demands one, add it to
  `EXTRA_FIELDS` at the top of the file and it rides along with every update.
  There is no such field on the Deals module today under the obvious API
  names, and Closed Lost records already exist, so this is a just-in-case.
- **Blueprint** on the Deals layout. A Blueprint forces stage movement through
  transitions and blocks a direct API stage write. Set `SKIP_WORKFLOWS = true`
  in the API version, or exclude Blueprint-bound Deals from the filter.
- **Workflow rules** that fire on stage change. They still run unless you set
  `SKIP_WORKFLOWS = true`, which is usually what you want for a clean-up job,
  but check that no revenue or forecast automation depends on them.
- **Record locking** or field-level permissions on Stage for the executing
  user.
