# Draft Engine Phase 5 Validation Report

- Generated: `2026-02-21T07:58:57.020311+00:00`
- Maps evaluated: `30` / requested `30`
- Method: hit if recommendation intersects remaining ground-truth picks/bans at each draft micro-step

## Summary

| Metric | v1 | v2 | Delta (v2-v1) |
|---|---:|---:|---:|
| Pick Hit Rate | 0.8633 | 0.8533 | -0.0100 |
| Pick Top1 Rate | 0.2933 | 0.3700 | +0.0767 |
| Ban Hit Rate | 0.6767 | 0.7633 | +0.0866 |
| Ban Top1 Rate | 0.0767 | 0.0667 | -0.0100 |

## Feasibility (v2)

- Checks: `600`
- Ally infeasible rate: `0.0033`
- Enemy infeasible rate: `0.0000`

## Notes

- Hit-rate dipakai sebagai proxy objektif dari relevansi rekomendasi ke data historis.
- Top1-rate menggambarkan kualitas ranking hero rekomendasi teratas.
- Untuk validasi coaching quality final, tetap perlu uji playtest user secara manual di UI.
