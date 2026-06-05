# PrintLab Plus Printer Orca Onboarding Design

## Purpose

PrintLab Plus should reuse printers already configured in PrintLab while adding the extra slicer profile information Orca needs. Users should not re-enter printer connection details. Printers added through environment configuration or through the existing in-app printer flow should appear in PrintLab Plus automatically, then ask for Orca-specific profile details only when those details are missing.

## Scope

This design covers printer discovery, profile-binding storage, onboarding prompts, and slicer command data flow for PrintLab Plus. It does not change how PrintLab stores printer connection credentials, nor does it require users to maintain a separate Plus-only printer list.

## Current System Context

PrintLab already supports printers from two sources:

- Environment-backed printer configuration, including the multi-printer JSON configuration.
- In-app printer creation and editing through `/api/printers`.

Those records contain connection and operational metadata such as printer id, name, host, serial, access code, device type, MQTT mode, camera mode, and SSL verification settings.

Orca needs different data to slice correctly: machine preset, nozzle size, bed and firmware characteristics, AMS or extruder setup, filament presets, and process presets. The recent Orca Docker smoke work confirmed this gap: the binary can run and inspect/export simple model data, but full slicing fails without compatible machine, process, and filament preset context.

## Recommended Approach

PrintLab Plus should treat the existing PrintLab printer registry as the source of truth for printer connection records. Plus should add a separate Orca profile binding for each printer that needs slicing.

This avoids duplicate printer setup while keeping slicer configuration separate from connection credentials.

## Data Model

Add a PrintLab Plus Orca binding record keyed by `printer_id`.

Suggested fields:

```text
printer_id
orca_machine_preset
nozzle_diameter
ams_enabled
filament_presets
process_preset
profile_confirmed_at
profile_source
updated_at
```

`printer_id` links to the existing PrintLab printer record.

`profile_source` records whether the profile was auto-mapped from `device_type`, confirmed by the user, or manually edited later.

`profile_confirmed_at` being absent means the printer should be shown as needing slicer setup.

## Printer Discovery Flow

PrintLab Plus lists printers by reading the same printer manager used by the existing app.

For every printer:

1. Load the existing PrintLab printer record.
2. Look for a matching Orca binding by `printer_id`.
3. If no binding exists, create or display a pending binding state.
4. If `device_type` maps to a known Orca machine preset, prefill that machine preset.
5. Mark the printer as `Needs slicer profile` until required Orca fields are confirmed.

This flow applies both on startup and when printers are added over time. A printer added through `.env` or the app API should appear in Plus without a manual import step.

## Onboarding Trigger Points

PrintLab Plus should ask for Orca setup only when it is useful.

Trigger onboarding when:

- The user opens the slicer with a target printer selected and that printer has no confirmed Orca binding.
- The user tries to route a sliced artifact to a printer with no confirmed Orca binding.
- The user opens the Plus printer list and chooses a printer marked `Needs slicer profile`.

Do not block normal printer monitoring or queue visibility just because the Orca profile is missing.

## Onboarding Fields

The first version should ask for the minimum required slicer fields:

- Orca machine preset.
- Nozzle diameter.
- AMS enabled or disabled.
- Filament preset or presets.
- Process preset.

When `device_type` maps cleanly to a known machine preset, preselect it. The user still confirms before the binding becomes active.

## Slicer Data Flow

When a slicer job targets a printer:

1. Resolve the PrintLab printer by `printer_id`.
2. Resolve the confirmed Orca binding for that printer.
3. Reject slicing with a clear setup-required response if the binding is missing or incomplete.
4. Build the Orca invocation from the selected model plus the printer's machine, filament, and process presets.
5. Persist the slicer job manifest with both the PrintLab printer id and the resolved Orca preset names.

The saved output artifact remains the source of truth for routing to the printer queue.

## Error Handling

If a printer exists but has no Orca binding, return a setup-required state rather than a generic slicer failure.

If a binding references an Orca preset that is no longer available in the installed Orca profile set, mark the binding stale and prompt the user to reselect the missing preset.

If a printer is removed from PrintLab, the Plus binding should no longer appear in active printer lists. The binding may be retained for audit or future restoration, but it should not be used for slicing.

## Testing

Add focused tests for:

- Environment-backed printers appear in Plus as pending Orca setup.
- In-app-created printers appear in Plus as pending Orca setup.
- A known `device_type` preselects a likely Orca machine preset.
- Slicing with an unconfirmed binding returns setup-required.
- Slicing with a confirmed binding includes machine, filament, and process preset data in the Orca command manifest.
- Removing a printer hides or disables its Orca binding in Plus views.

## Success Criteria

- Users do not re-enter existing printer connection details in PrintLab Plus.
- Printers added through `.env` or the existing app appear in Plus automatically.
- Missing Orca profile data is requested only when needed.
- Orca slicing receives printer-specific machine, process, and filament context.
- The implementation stays separate enough that PrintLab Plus can evolve without forcing the main PrintLab branch to become the slicer product.
