---
id: models
title: Model Profiles
summary: The Model Profiles of this installation and how a manifest names one.
---
A manifest names a Model Profile in `environment.model.profile`, never a raw model id. The profile is a row of this installation's Model Catalog: it fixes the vendor, the exact model id, the context window, the list prices and the most sensitive data class the model may see.

A lane runs a profile only when it routes the profile's vendor. `native` and `emulated` run; `unsupported` is refused (`MODEL_ROUTE_UNSUPPORTED`); `unbound` means the installation binds no credential for that lane.

Choose a different profile for the judge than for the producer, and prefer a different vendor for the judge. Check the context window and the price before you set `environment.budget`.

{{generated}}

Read one profile with {op:describe_model}: window, prices, what it supports and every lane's route verdict. List them with {op:list_models}; pass a lane profile to keep only the profiles that lane routes.
