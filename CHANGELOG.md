# Changelog

## [1.0.0](https://github.com/KRoperUK/smeg-plus-patches/compare/v0.3.0...v1.0.0) (2026-09-14)


### ⚠ BREAKING CHANGES

* the repository and Python distribution are renamed.

### Features

* an asset catalogue, so customising is a choice rather than a hunt ([#84](https://github.com/KRoperUK/smeg-plus-patches/issues/84)) ([5dff268](https://github.com/KRoperUK/smeg-plus-patches/commit/5dff268382f982392243ce9b840a423c3cf8bb88))
* diagnostic build that turns the application's own logging back on ([#70](https://github.com/KRoperUK/smeg-plus-patches/issues/70)) ([e5dfadb](https://github.com/KRoperUK/smeg-plus-patches/commit/e5dfadb1b5abd6fdfc19b0b07a7965ec3b0bad40))
* force AUX as the default source, as a data edit ([#73](https://github.com/KRoperUK/smeg-plus-patches/issues/73)) ([c942278](https://github.com/KRoperUK/smeg-plus-patches/commit/c942278c8bfe283435c908cff971ee0a79cda0c8))
* force AUX on boot by patching C_MGR_SRC::StartUp restore ([#111](https://github.com/KRoperUK/smeg-plus-patches/issues/111)) ([8acb53a](https://github.com/KRoperUK/smeg-plus-patches/commit/8acb53a7a7eb60bc4e55e0b60379501999d8e2a5))
* hardware-verified flash, custom media tooling, and a manifest build ([#56](https://github.com/KRoperUK/smeg-plus-patches/issues/56)) ([91bb341](https://github.com/KRoperUK/smeg-plus-patches/commit/91bb3415ff22ac6cd73e631af59daf83debf74a0))
* make the firmware's logging emit, and document the AUX chain gate by gate ([#87](https://github.com/KRoperUK/smeg-plus-patches/issues/87)) ([0acb6b6](https://github.com/KRoperUK/smeg-plus-patches/commit/0acb6b6d766aec7c46b0f04754fce2846f87f60d))
* point the logging sink at VxWorks logMsg, whose address is now known ([#95](https://github.com/KRoperUK/smeg-plus-patches/issues/95)) ([d1188b5](https://github.com/KRoperUK/smeg-plus-patches/commit/d1188b5802d2bc4ecf9837a67534e799f41eb343))
* pre-flight a package, and fail the build if it would not work ([#78](https://github.com/KRoperUK/smeg-plus-patches/issues/78)) ([2bfd1a5](https://github.com/KRoperUK/smeg-plus-patches/commit/2bfd1a57782304fddfbbe519ac2162e5a7834d6e))
* re-seal contract.dat so patched packages are accepted ([#54](https://github.com/KRoperUK/smeg-plus-patches/issues/54)) ([660cb5b](https://github.com/KRoperUK/smeg-plus-patches/commit/660cb5bd475410125636c052e048fc3a60cf8dc8)), closes [#53](https://github.com/KRoperUK/smeg-plus-patches/issues/53)
* read the symbol tables the package has been shipping all along ([#90](https://github.com/KRoperUK/smeg-plus-patches/issues/90)) ([279a73c](https://github.com/KRoperUK/smeg-plus-patches/commit/279a73cc62900d65484b82630364010c62595b0a))
* retry the AUX default with a correct folder name and a did-it-apply beacon ([#99](https://github.com/KRoperUK/smeg-plus-patches/issues/99)) ([fd19db1](https://github.com/KRoperUK/smeg-plus-patches/commit/fd19db14051428eacef650ced129f351b46084fd))
* run firmware functions on an emulated CPU, and correct what that disproves ([#86](https://github.com/KRoperUK/smeg-plus-patches/issues/86)) ([5bf160c](https://github.com/KRoperUK/smeg-plus-patches/commit/5bf160cc6ec36d52a7e0bbf5be63cf5bf68097c7))
* ship a USER_DATA payload, where the unit actually reads its settings ([#74](https://github.com/KRoperUK/smeg-plus-patches/issues/74)) ([792c76d](https://github.com/KRoperUK/smeg-plus-patches/commit/792c76d3c87cfbd32698f8ced30a50ba5e55b738))
* spy collect also backs up /USER_DATA to the stick ([#108](https://github.com/KRoperUK/smeg-plus-patches/issues/108)) ([25271b6](https://github.com/KRoperUK/smeg-plus-patches/commit/25271b69da2cec7532463c3ab337ca65f68b89d0))
* **studio:** follow the desktop's light or dark scheme ([#76](https://github.com/KRoperUK/smeg-plus-patches/issues/76)) ([c990152](https://github.com/KRoperUK/smeg-plus-patches/commit/c990152e64606dc6f173956ca9c9a270ba7b1971))
* **studio:** icon buttons instead of text ([#71](https://github.com/KRoperUK/smeg-plus-patches/issues/71)) ([2878626](https://github.com/KRoperUK/smeg-plus-patches/commit/2878626ed78b003f6be0a47741c9c9012d1232ff))
* verify the USER_DATA FAT long filename before flashing ([#106](https://github.com/KRoperUK/smeg-plus-patches/issues/106)) ([3627aef](https://github.com/KRoperUK/smeg-plus-patches/commit/3627aef079d77540d69bebf0aa93eebdcf6865fc))


### Bug Fixes

* apply each patch set to the package being built, not the stock source ([#113](https://github.com/KRoperUK/smeg-plus-patches/issues/113)) ([e1b5156](https://github.com/KRoperUK/smeg-plus-patches/commit/e1b5156890492801051da97e08aa25701610aecc))
* aux-sticky dropped a branch condition and could never select AUX ([#89](https://github.com/KRoperUK/smeg-plus-patches/issues/89)) ([d49f274](https://github.com/KRoperUK/smeg-plus-patches/commit/d49f2741fb57d274f95b4e1ac691c50639961096))
* build complete USER_DATA database payloads ([#105](https://github.com/KRoperUK/smeg-plus-patches/issues/105)) ([ba45a30](https://github.com/KRoperUK/smeg-plus-patches/commit/ba45a3068b86b354067cb29a637d628255d4640b))
* close every file these tools and tests open ([#93](https://github.com/KRoperUK/smeg-plus-patches/issues/93)) ([69b9e5b](https://github.com/KRoperUK/smeg-plus-patches/commit/69b9e5b3b2c53517eeb7a4394b81065204e7639a))
* fail pre-flight when a USER_DATA payload sits where the updater cannot read it ([#114](https://github.com/KRoperUK/smeg-plus-patches/issues/114)) ([83bf9dc](https://github.com/KRoperUK/smeg-plus-patches/commit/83bf9dc6c1ebe30d71e10d6fae450025fe05ea66))
* guard patches by firmware version, and report it in pre-flight ([#103](https://github.com/KRoperUK/smeg-plus-patches/issues/103)) ([96ff297](https://github.com/KRoperUK/smeg-plus-patches/commit/96ff2975d40bb3073e2d618884108d9e3eab9bc7))
* the logging sink is a stub, so neither diagnostic patch produces output ([#92](https://github.com/KRoperUK/smeg-plus-patches/issues/92)) ([b1ae396](https://github.com/KRoperUK/smeg-plus-patches/commit/b1ae396185b88760fc122d08ee67305930c78d8d))
* warn when a USER_DATA payload sits at a path the updater will not read ([#97](https://github.com/KRoperUK/smeg-plus-patches/issues/97)) ([b837f0f](https://github.com/KRoperUK/smeg-plus-patches/commit/b837f0fc3ac66f17f8b7f9363a408881ace42ccf))


### Documentation

* addresses are per firmware version, and the cheatcode screen is reachable ([#102](https://github.com/KRoperUK/smeg-plus-patches/issues/102)) ([7d043b8](https://github.com/KRoperUK/smeg-plus-patches/commit/7d043b888bef1c41284e6026f5e720c726bd6847))
* bring the site's name, title and homepage up to what the project is ([#80](https://github.com/KRoperUK/smeg-plus-patches/issues/80)) ([49ac3db](https://github.com/KRoperUK/smeg-plus-patches/commit/49ac3db45d3345b11bebcb5631dc4595f1936593))
* correct the studio's filename everywhere, and the venv that is not there ([#85](https://github.com/KRoperUK/smeg-plus-patches/issues/85)) ([48fe436](https://github.com/KRoperUK/smeg-plus-patches/commit/48fe4368e15553fbd6b0ba3df5929264d9d4defa))
* diagram the media contract with mermaid ([#55](https://github.com/KRoperUK/smeg-plus-patches/issues/55)) ([07969b0](https://github.com/KRoperUK/smeg-plus-patches/commit/07969b03dcff633979de022411d65205175d554d))
* fix how Last_Source is matched, and pin the source id enum ([#100](https://github.com/KRoperUK/smeg-plus-patches/issues/100)) ([f1558fa](https://github.com/KRoperUK/smeg-plus-patches/commit/f1558fab36f8ec208a55f6c5c49a3e9da4ed2df1))
* inventory every customisable asset in the unit ([#83](https://github.com/KRoperUK/smeg-plus-patches/issues/83)) ([1d27c17](https://github.com/KRoperUK/smeg-plus-patches/commit/1d27c17d0b27f398283cb2db066d1bd6e8696cb7))
* record what is reachable and what is not, and why ([#75](https://github.com/KRoperUK/smeg-plus-patches/issues/75)) ([2386c61](https://github.com/KRoperUK/smeg-plus-patches/commit/2386c61b056d49d537f79d2455079f261b60d508))
* restructure site by firmware artefact and add zensical diagrams, tabs and cards ([#110](https://github.com/KRoperUK/smeg-plus-patches/issues/110)) ([6914422](https://github.com/KRoperUK/smeg-plus-patches/commit/6914422c6c5222254f72df6db6d553864dd2e06c))
* spy-dump-userdata is confirmed on hardware ([#109](https://github.com/KRoperUK/smeg-plus-patches/issues/109)) ([412c340](https://github.com/KRoperUK/smeg-plus-patches/commit/412c340820ddf96ccb7f1f1553ee9411feb92a5d))
* the media contract blocks modified firmware ([#52](https://github.com/KRoperUK/smeg-plus-patches/issues/52)) ([215eb8c](https://github.com/KRoperUK/smeg-plus-patches/commit/215eb8ce842ab8c64413b070593077d34b7cb36d)), closes [#51](https://github.com/KRoperUK/smeg-plus-patches/issues/51)
* the release PR's approval click is expected, and not for agents to automate ([#69](https://github.com/KRoperUK/smeg-plus-patches/issues/69)) ([f6d1b71](https://github.com/KRoperUK/smeg-plus-patches/commit/f6d1b71defb051c45ef1f3e20ada8c9390921d9c))
* the spy path bypasses the log sink, and the USER_DATA retry still did not apply ([#101](https://github.com/KRoperUK/smeg-plus-patches/issues/101)) ([d51c850](https://github.com/KRoperUK/smeg-plus-patches/commit/d51c850f1174edfd5fc705164d659aa94a2e1e97))
* the studio has been run, not just written ([#50](https://github.com/KRoperUK/smeg-plus-patches/issues/50)) ([3845ba3](https://github.com/KRoperUK/smeg-plus-patches/commit/3845ba3b4822d5f163a0b9caa90ee052e5a229cb))
* the user POI database, which is the better lead for speed cameras ([#82](https://github.com/KRoperUK/smeg-plus-patches/issues/82)) ([fcb0902](https://github.com/KRoperUK/smeg-plus-patches/commit/fcb0902331ba583c6165fe6c406b2a036fd3e0eb))
* three source numberings, and stop asserting which one Last_Source uses ([#98](https://github.com/KRoperUK/smeg-plus-patches/issues/98)) ([808499c](https://github.com/KRoperUK/smeg-plus-patches/commit/808499c4248dabddba05d46794a2105cd5bd93ec))
* write down the gotchas that have each cost time here ([#81](https://github.com/KRoperUK/smeg-plus-patches/issues/81)) ([81299e4](https://github.com/KRoperUK/smeg-plus-patches/commit/81299e4aacaecc79b134cd2992d5a0e084e8fa36))

## [0.3.0](https://github.com/KRoperUK/smeg-plus-patches/compare/v0.2.0...v0.3.0) (2026-09-12)


### Features

* preview ring tones from the studio ([#46](https://github.com/KRoperUK/smeg-plus-patches/issues/46)) ([f7c72c9](https://github.com/KRoperUK/smeg-plus-patches/commit/f7c72c986bb61a996052a8e1321e9f2fbc8fd341))


### Documentation

* add AGENTS.md and agent instructions ([#47](https://github.com/KRoperUK/smeg-plus-patches/issues/47)) ([395283f](https://github.com/KRoperUK/smeg-plus-patches/commit/395283ffa45be58399eb7c15a3abc21b6ff9ddae))

## [0.2.0](https://github.com/KRoperUK/smeg-plus-patches/compare/v0.1.0...v0.2.0) (2026-09-12)


### Features

* add always-available and sticky AUX patch definitions ([#30](https://github.com/KRoperUK/smeg-plus-patches/issues/30)) ([e3593cf](https://github.com/KRoperUK/smeg-plus-patches/commit/e3593cf801bdf77659fa8e9c223370e5574765b7))
* add ringtone converter and Qt studio ([#31](https://github.com/KRoperUK/smeg-plus-patches/issues/31)) ([9e71ffc](https://github.com/KRoperUK/smeg-plus-patches/commit/9e71ffc7bc5da4f4668eb7476051864d9aaa587e))
* media-partition patcher, ringtone UI, and uv support ([#42](https://github.com/KRoperUK/smeg-plus-patches/issues/42)) ([adeb3e5](https://github.com/KRoperUK/smeg-plus-patches/commit/adeb3e5e5b4c80495c1ff6b2ef2584ee404a15a0)), closes [#35](https://github.com/KRoperUK/smeg-plus-patches/issues/35) [#36](https://github.com/KRoperUK/smeg-plus-patches/issues/36) [#37](https://github.com/KRoperUK/smeg-plus-patches/issues/37)
* modernise the Ringtone Studio UI ([#33](https://github.com/KRoperUK/smeg-plus-patches/issues/33)) ([beb6e77](https://github.com/KRoperUK/smeg-plus-patches/commit/beb6e7719e63e69e53a44be2c15592a4e2979cbf))


### Bug Fixes

* validate the media tree in ringtones.py stage, and refresh the docs ([#41](https://github.com/KRoperUK/smeg-plus-patches/issues/41)) ([4a5712f](https://github.com/KRoperUK/smeg-plus-patches/commit/4a5712f23424ddc30dbced999c36872a404b12d7)), closes [#40](https://github.com/KRoperUK/smeg-plus-patches/issues/40)


### Documentation

* the media-partition SIZE fields are solved ([#34](https://github.com/KRoperUK/smeg-plus-patches/issues/34)) ([baa7e93](https://github.com/KRoperUK/smeg-plus-patches/commit/baa7e936737b2309acbffd8c78ed653a45200d8c))
