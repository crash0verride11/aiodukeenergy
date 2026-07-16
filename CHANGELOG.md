# Changelog

## v1.2.0 (2026-07-16)

### Documentation

- Fix type checking mypi failures ([`358cd69`](https://github.com/crash0verride11/aiodukeenergy/commit/358cd69749e65a495b8ed4def95f4700484f9948))
- Example get_monthly_usage and get_billing_payment_info methods ([`24f581a`](https://github.com/crash0verride11/aiodukeenergy/commit/24f581a39cd54189b4bc82bf606b8520cc81ed4a))
- Add get_billing_payment_info ([`8134ecc`](https://github.com/crash0verride11/aiodukeenergy/commit/8134ecc97a3420f19f4555954ec05baf9ddec5e4))

### Testing

- Usage_len check fixes ([`3e3bb7c`](https://github.com/crash0verride11/aiodukeenergy/commit/3e3bb7c28d03053c73ddce66a482c58f94744d26))
- Get_billing_payment_info ([`2300b76`](https://github.com/crash0verride11/aiodukeenergy/commit/2300b766058bf73abf69e4f3b27698ce99d83308))
- Uv.lock ([`c18a256`](https://github.com/crash0verride11/aiodukeenergy/commit/c18a256b5e0aa03582fda94a75e30efb85229f8d))

### Bug fixes

- Usage_len regression ([`d642826`](https://github.com/crash0verride11/aiodukeenergy/commit/d6428269891ab97a29668e598a6c30d7f7fabd7c))

### Features

- Billing_payment_info ([`5ebbd31`](https://github.com/crash0verride11/aiodukeenergy/commit/5ebbd31c51210580a8b43c9a7956a21766390495))

### Refactoring

- Add monthly get_energy_usage ([`56cd512`](https://github.com/crash0verride11/aiodukeenergy/commit/56cd512ac8109875a83af736daf8d2383961eca7))

## v1.1.0 (2026-07-13)

### Refactoring

- Commit lint validation ([`15cb240`](https://github.com/crash0verride11/aiodukeenergy/commit/15cb2408fcc86aafd5136a2f99aeea1e0b16fa15))
- Add get_invoice to use in get_monthly_usage ([`13c4f46`](https://github.com/crash0verride11/aiodukeenergy/commit/13c4f468ecdf3b8b8c3d785b474be6278be621c7))

### Testing

- Get_invoice_list ([`d01eabf`](https://github.com/crash0verride11/aiodukeenergy/commit/d01eabfa1d27ac7bb7e8de80ad3b9c1b9ce85035))

### Documentation

- New get_invoices method ([`6b95556`](https://github.com/crash0verride11/aiodukeenergy/commit/6b95556113f95d3c4dfbe6bdc3c5650ff353b18c))

### Features

- Add usage/monthly endpoint ([`955590c`](https://github.com/crash0verride11/aiodukeenergy/commit/955590cf0d33a07cd18bfce698fd3ad748e5f9dc))

## v1.0.0 (2026-07-12)

### Features

- Cma-prod support ([`cac45e8`](https://github.com/crash0verride11/aiodukeenergy/commit/cac45e8c057959b2b24a0ef1c36f30ebbb643e47))
- Safari-extension for macos users ([`b8fe790`](https://github.com/crash0verride11/aiodukeenergy/commit/b8fe790a2a62ee915f869a5595ec76faeccf453e))
- Try version bump again to trigger release ([`c1f073d`](https://github.com/crash0verride11/aiodukeenergy/commit/c1f073dceac481580235be0fe626aa3c4d8acc35))
- Implement new api response and fix duplicate hour handling (#9) ([`ebfeaab`](https://github.com/crash0verride11/aiodukeenergy/commit/ebfeaab8c2806abdba13cb1ae8e376039b37caf7))
- Allow directly calling authenticate (#2) ([`cde5d87`](https://github.com/crash0verride11/aiodukeenergy/commit/cde5d87daea32c40101cc7ef3cf8be7e9f257bbe))
- First version (#1) ([`9369c78`](https://github.com/crash0verride11/aiodukeenergy/commit/9369c787a0efd0f84cb7b81d5a43da1a486861ea))

### Bug fixes

- Readme numbering ([`d89c1ca`](https://github.com/crash0verride11/aiodukeenergy/commit/d89c1ca4790f07db7da36634a974f9a61fd26156))
- Readme lint ([`704f502`](https://github.com/crash0verride11/aiodukeenergy/commit/704f502173728b335e00221c81594924bc00b22c))
- Pre-commit check ([`9c4c792`](https://github.com/crash0verride11/aiodukeenergy/commit/9c4c79282a0e72ed34b6830710aa7003ef7c3bbc))
- Expected_series format check for daily values (#15) ([`5c8aa42`](https://github.com/crash0verride11/aiodukeenergy/commit/5c8aa422d77c40d9b6c89f8753ef66eb04ea0434))
- Update deprecated paths (#8) ([`7509d34`](https://github.com/crash0verride11/aiodukeenergy/commit/7509d34a96edd7c17f5720c89f77fe68a0306302))
- Missing hours come back sometimes that we need to handle (#4) ([`5bd3836`](https://github.com/crash0verride11/aiodukeenergy/commit/5bd38363f0661399d0ca65ea22a66a7dfcec9bf9))
- Fix return types for get_meters and get_accounts (#3) ([`da29eca`](https://github.com/crash0verride11/aiodukeenergy/commit/da29eca72ded229b6a9717251a54633ecc873291))

### Refactoring

- Ios authentication and endpoints (#17) ([`c85d7c0`](https://github.com/crash0verride11/aiodukeenergy/commit/c85d7c0a72d5c4f40d98eed20a3a3c7c81ae7043))
- Implement auth change to auth0 (#13) ([`eba6c40`](https://github.com/crash0verride11/aiodukeenergy/commit/eba6c40a289777d0f13da376c243674b99df2da1))

### Code style

- Apply ruff format ([`cccb745`](https://github.com/crash0verride11/aiodukeenergy/commit/cccb745bab712c7c06e18872e490637a8d418a86))
