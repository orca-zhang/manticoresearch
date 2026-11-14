# Final adaptive cache measurement tables

All random-query columns use the same final binary. QPS multipliers use cache off in the same case; these are configuration comparisons, not full-PR speedups over upstream.

| Rows | Configuration | QPS | QPS / off | Server CPU ms/query | CPU vs off | Charged / mapped MiB |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 20,000 | Cache off | 6,203.8 | 1.000× | 1.0896 | +0.00% | 0.0 / 0.0 |
| 20,000 | Adaptive 16 MiB (default) | 8,224.6 | 1.326× | 0.8154 | -25.17% | 2.5 / 3.6 |
| 20,000 | Adaptive 128 MiB | 8,038.2 | 1.296× | 0.8357 | -23.31% | 2.5 / 3.6 |
| 20,000 | Fixed 512 MiB (reference) | 8,297.8 | 1.338× | 0.8090 | -25.75% | 2.5 / 0.0 |
| 20,000 | Adaptive 512 MiB | 8,056.4 | 1.299× | 0.8332 | -23.53% | 2.5 / 3.6 |
| 100,000 | Cache off | 5,441.6 | 1.000× | 1.2683 | +0.00% | 0.0 / 0.0 |
| 100,000 | Adaptive 16 MiB (default) | 7,232.9 | 1.329× | 0.9482 | -25.24% | 12.6 / 16.8 |
| 100,000 | Adaptive 128 MiB | 7,231.5 | 1.329× | 0.9463 | -25.39% | 12.6 / 16.8 |
| 100,000 | Fixed 512 MiB (reference) | 7,278.6 | 1.338× | 0.9429 | -25.66% | 12.6 / 0.0 |
| 100,000 | Adaptive 512 MiB | 7,291.8 | 1.340× | 0.9360 | -26.20% | 12.6 / 16.8 |
| 1,000,000 | Cache off | 3,397.0 | 1.000× | 2.1540 | +0.00% | 0.0 / 0.0 |
| 1,000,000 | Adaptive 16 MiB (default) | 3,024.9 | 0.890× | 2.3996 | +11.40% | 15.8 / 22.0 |
| 1,000,000 | Adaptive 128 MiB | 5,250.3 | 1.546× | 1.3655 | -36.61% | 124.6 / 161.1 |
| 1,000,000 | Fixed 512 MiB (reference) | 5,386.9 | 1.586× | 1.3300 | -38.26% | 125.5 / 0.0 |
| 1,000,000 | Adaptive 512 MiB | 5,334.3 | 1.570× | 1.3434 | -37.63% | 126.5 / 163.2 |
| 5,000,000 | Cache off | 1,759.0 | 1.000× | 4.3439 | +0.00% | 0.0 / 0.0 |
| 5,000,000 | Adaptive 16 MiB (default) | 1,698.8 | 0.966× | 4.5111 | +3.85% | 15.8 / 22.0 |
| 5,000,000 | Adaptive 128 MiB | 1,763.0 | 1.002× | 4.3461 | +0.05% | 128.0 / 166.1 |
| 5,000,000 | Fixed 512 MiB (reference) | 2,108.2 | 1.199× | 3.6503 | -15.97% | 511.8 / 0.0 |
| 5,000,000 | Adaptive 512 MiB | 2,094.2 | 1.191× | 3.6697 | -15.52% | 511.8 / 660.3 |
| 20,000,000 | Cache off | 742.7 | 1.000× | 10.5099 | +0.00% | 0.0 / 0.0 |
| 20,000,000 | Adaptive 16 MiB (default) | 726.2 | 0.978× | 10.7482 | +2.27% | 15.8 / 21.7 |
| 20,000,000 | Adaptive 128 MiB | 733.8 | 0.988× | 10.6609 | +1.44% | 128.0 / 166.1 |
| 20,000,000 | Fixed 512 MiB (reference) | 731.3 | 0.985× | 10.6904 | +1.72% | 511.8 / 0.0 |
| 20,000,000 | Adaptive 512 MiB | 756.5 | 1.019× | 10.3466 | -1.55% | 511.8 / 660.3 |

## Memory stage endpoints

| Pass | Configuration | Access phase | Charged MiB | Mapped MiB | RSS MiB | Physical footprint MiB |
| ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | Fixed 512 MiB (reference) | broad | 511.8 | 0.0 | 773.0 | 695.3 |
| 1 | Fixed 512 MiB (reference) | hot | 511.8 | 0.0 | 773.4 | 695.8 |
| 1 | Fixed 512 MiB (reference) | broad-again | 511.8 | 0.0 | 773.9 | 696.3 |
| 1 | Adaptive 512 MiB | broad | 511.8 | 660.3 | 767.2 | 689.5 |
| 1 | Adaptive 512 MiB | hot | 15.8 | 59.3 | 167.5 | 89.9 |
| 1 | Adaptive 512 MiB | broad-again | 511.8 | 660.1 | 769.1 | 691.5 |
| 2 | Adaptive 512 MiB | broad | 511.8 | 660.1 | 767.3 | 689.7 |
| 2 | Adaptive 512 MiB | hot | 15.8 | 60.0 | 168.3 | 90.7 |
| 2 | Adaptive 512 MiB | broad-again | 511.8 | 660.1 | 768.3 | 690.7 |
| 2 | Fixed 512 MiB (reference) | broad | 511.8 | 0.0 | 772.0 | 694.3 |
| 2 | Fixed 512 MiB (reference) | hot | 511.8 | 0.0 | 772.4 | 694.8 |
| 2 | Fixed 512 MiB (reference) | broad-again | 511.8 | 0.0 | 774.1 | 696.5 |

## Independent controls

| Workload | Configuration | QPS | Server CPU ms/query |
| --- | --- | ---: | ---: |
| random-20000000 | off-A | 744.9 | 10.5086 |
| random-20000000 | off-B | 747.9 | 10.4572 |
| scan-20000000 | Cache off | 5,154.4 | 1.1556 |
| scan-20000000 | Adaptive 16 MiB (default) | 7,457.4 | 0.7601 |
| scan-20000000 | Adaptive 128 MiB | 7,513.8 | 0.7592 |
| scan-20000000 | Fixed 512 MiB (reference) | 7,521.9 | 0.7569 |
| scan-20000000 | Adaptive 512 MiB | 7,545.7 | 0.7566 |
