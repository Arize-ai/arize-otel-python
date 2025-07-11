# Changelog

## [0.9.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.8.2...arize-otel-python/v0.9.0) (2025-07-08)


### 🎁 New Features

* add Python 3.13 support ([#48947](https://github.com/Arize-ai/arize/issues/48947)) ([8699a15](https://github.com/Arize-ai/arize/commit/8699a153086c95693ca0e93e36eeebc4155f062a))

## [0.8.2](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.8.1...arize-otel-python/v0.8.2) (2025-06-04)


### 🐛 Bug Fixes

* handle attribute change in opentelemetry-exporter-otlp ([#47227](https://github.com/Arize-ai/arize/issues/47227)) ([fc2d484](https://github.com/Arize-ai/arize/commit/fc2d4841e36f4a30a37a2407b2d60b910135e24b))

## [0.8.1](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.8.0...arize-otel-python/v0.8.1) (2025-04-14)


### 🐛 Bug Fixes

* Add headers and mark underscored headers for deprecation ([#44341](https://github.com/Arize-ai/arize/issues/44341)) ([5642910](https://github.com/Arize-ai/arize/commit/5642910b26c3d82707b0128d31be48ef40b43edd))

## [0.8.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.7.3...arize-otel-python/v0.8.0) (2025-02-07)


### 🎁 New Features

* Use Open Inference Tracer Provider in register otel ([#41342](https://github.com/Arize-ai/arize/issues/41342)) ([08309c1](https://github.com/Arize-ai/arize/commit/08309c19662ca1bcf2f8cb1fc3ad9eb54085a660))

## [0.7.3](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.7.2...arize-otel-python/v0.7.3) (2025-01-21)


### 🐛 Bug Fixes

* Set global tracer by default ([#40477](https://github.com/Arize-ai/arize/issues/40477)) ([3eafe8a](https://github.com/Arize-ai/arize/commit/3eafe8a9494e9b5aae71ba76dbc59b5e4e7c0043))

## [0.7.2](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.7.1...arize-otel-python/v0.7.2) (2025-01-14)


### 📚 Documentation

* Improve README ([#40209](https://github.com/Arize-ai/arize/issues/40209)) ([1a90375](https://github.com/Arize-ai/arize/commit/1a9037575b0631025d6046f1fc38cb7e94ba8a25))

## [0.7.1](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.7.0...arize-otel-python/v0.7.1) (2024-12-13)


### 📚 Documentation

* fix README typos for endpoint input field ([#39272](https://github.com/Arize-ai/arize/issues/39272)) ([3c4a120](https://github.com/Arize-ai/arize/commit/3c4a120fd3ec6b9b8884542e707c781ddb600d68))

## [0.7.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.6.0...arize-otel-python/v0.7.0) (2024-12-11)


### ⚠ BREAKING CHANGES

* Remove `space_key` authentication ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Change import to `from arize.otel import ...` ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Rename endpoint class to `Endpoint` instead of `Endpoints` ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Rename `register_otel` as `register` ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* `register` does not take multiple endpoints, just one ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Remove `model_id` from `register`. Use `project_name` ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Remove `model_version` from `register` ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Remove `phoenix` related endpoints ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Remove `space_key` authentication ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))

### 🎁 New Features

* Make arize-otel package a wrapper around otel primitives ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Ability to pass the `transport` method via the `Transport` enum ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))
* Ability to configure using environment variables ([#38838](https://github.com/Arize-ai/arize/issues/38838)) ([d7f36a4](https://github.com/Arize-ai/arize/commit/d7f36a42bbef79d686931ac2e8b5ceb324a8c7ff))

## [0.6.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.5.3...arize-otel-python/v0.6.0) (2024-12-04)


### 🎁 New Features

* Add support for project_name when logging to Arize ([#38834](https://github.com/Arize-ai/arize/issues/38834)) ([09c9efa](https://github.com/Arize-ai/arize/commit/09c9efad726f4d39ee11074123baf80805389650))


### 🐛 Bug Fixes

* `should_use_http` correct handling of custom endpoints ([09c9efa](https://github.com/Arize-ai/arize/commit/09c9efad726f4d39ee11074123baf80805389650))

## [0.5.3](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.5.2...arize-otel-python/v0.5.3) (2024-11-01)


### 🎨 Styles

* Use ruff as linter/formatter ([#37414](https://github.com/Arize-ai/arize/issues/37414)) ([95c9a35](https://github.com/Arize-ai/arize/commit/95c9a35a83654ac8847461bf2cbbb063e0abdcd8))

## [0.5.2](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.5.1...arize-otel-python/v0.5.2) (2024-09-13)
 

### 🐛 Bug Fixes

* auth_header_key sets only one of space_id or space_key ([#34266](https://github.com/Arize-ai/arize/issues/34266)) ([f58b0e1](https://github.com/Arize-ai/arize/commit/f58b0e1142a93e2a3eb59e5418741351242871a0))

## [0.5.1](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.5.0...arize-otel-python/v0.5.1) (2024-08-16)


### ❔ Miscellaneous Chores

* README reflects space_id changes ([#34225](https://github.com/Arize-ai/arize/issues/34225)) ([f03d0f0](https://github.com/Arize-ai/arize/commit/f03d0f0744066eb16cbf6eeda36e91be1460f5b7))

## [0.5.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.4.0...arize-otel-python/v0.5.0) (2024-08-15)


### 🎁 New Features

* send traces to Arize using OTLP exporter with space_id ([#33983](https://github.com/Arize-ai/arize/issues/33983)) ([74bf7cc](https://github.com/Arize-ai/arize/commit/74bf7cc905b9ac0a0fca603eb45ada1ee5a27386))

## [0.4.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.3.1...arize-otel-python/v0.4.0) (2024-08-09)


### 🎁 New Features

* Add local phoenix via grpc and http ([#33933](https://github.com/Arize-ai/arize/issues/33933)) ([d3617bb](https://github.com/Arize-ai/arize/commit/d3617bbca3fe438bcf20961ed2f2e6908cfc43c7))

## [0.3.1](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.3.0...arize-otel-python/v0.3.1) (2024-08-01)


### 🐛 Bug Fixes

* set `use_batch_processor` to be `True` by default ([#33677](https://github.com/Arize-ai/arize/issues/33677)) ([61be6bf](https://github.com/Arize-ai/arize/commit/61be6bf90af1ac167de99019ce546cbfe0974acf))

## [0.3.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.2.0...arize-otel-python/v0.3.0) (2024-07-30)


### 🎁 New Features

* Add batchprocessor option ([#33568](https://github.com/Arize-ai/arize/issues/33568)) ([b1f3d8c](https://github.com/Arize-ai/arize/commit/b1f3d8ce3e20e2a84bfe44ec3bfa058700662a5b))


### 🐛 Bug Fixes

* Accept string endpoints outside Endpoints Enum ([#33569](https://github.com/Arize-ai/arize/issues/33569)) ([b765bc9](https://github.com/Arize-ai/arize/commit/b765bc9b1b42839d271c4ca23ecfc10440ecc920))


### 📚 Documentation

* Fix Hosted Phoenix endpoint in README file ([#33507](https://github.com/Arize-ai/arize/issues/33507)) ([002f5c3](https://github.com/Arize-ai/arize/commit/002f5c335a4ee2fddcd03c9769f0120a14b1aff4))

## [0.2.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.1.1...arize-otel-python/v0.2.0) (2024-07-24)


### 🎁 New Features

* Add `HOSTED_PHOENIX` endpoint and export via http ([#33334](https://github.com/Arize-ai/arize/issues/33334)) ([10fd2af](https://github.com/Arize-ai/arize/commit/10fd2af5b5bb1124fd32378eeee001ecbd3ab20b))

## [0.1.1](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.1.0...arize-otel-python/v0.1.1) (2024-06-10)


### 📚 Documentation

* Fix README erratas ([#31711](https://github.com/Arize-ai/arize/issues/31711)) ([eeddf81](https://github.com/Arize-ai/arize/commit/eeddf819389256049b510d1e8d1ab99b08d12b8e))

## [0.1.0](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.0.1...arize-otel-python/v0.1.0) (2024-06-08)


### 🎁 New Features

* Add registration for arize, local phoenix, and custom endpoints ([#31619](https://github.com/Arize-ai/arize/issues/31619)) ([29594bb](https://github.com/Arize-ai/arize/commit/29594bb1b7918d6633633c039fcceb6857d01f80))


### 🐛 Bug Fixes

* Avoid camelcase in function name ([#31629](https://github.com/Arize-ai/arize/issues/31629)) ([89ad9d9](https://github.com/Arize-ai/arize/commit/89ad9d97d608dfa61b57366f4cb062b88baf0ef6))


### 📚 Documentation

* Add README and docstrings ([89ad9d9](https://github.com/Arize-ai/arize/commit/89ad9d97d608dfa61b57366f4cb062b88baf0ef6))


### 🔧 Build System

* Fix hatchling package handling ([#31661](https://github.com/Arize-ai/arize/issues/31661)) ([01a0ca8](https://github.com/Arize-ai/arize/commit/01a0ca8939d5325ce7eaf71fd7c7d5f83c8959cb))
* Add dependencies in pyproject.toml ([89ad9d9](https://github.com/Arize-ai/arize/commit/89ad9d97d608dfa61b57366f4cb062b88baf0ef6))
* Update build backend in pyproject.toml ([89ad9d9](https://github.com/Arize-ai/arize/commit/89ad9d97d608dfa61b57366f4cb062b88baf0ef6))
* Update metadata in pyproject.toml ([89ad9d9](https://github.com/Arize-ai/arize/commit/89ad9d97d608dfa61b57366f4cb062b88baf0ef6))

## [0.0.1](https://github.com/Arize-ai/arize/compare/arize-otel-python/v0.0.0...arize-otel-python/v0.0.1) (2024-06-06)


### 🐛 Bug Fixes

* Remove include in pyproject.toml ([#31610](https://github.com/Arize-ai/arize/issues/31610)) ([587679f](https://github.com/Arize-ai/arize/commit/587679f276501c9a789a204975111e3e40452ba0))

## 0.0.0 (2024-06-06)


### ❔ Miscellaneous Chores

* Initital package setup ([#31597](https://github.com/Arize-ai/arize/issues/31597)) ([0caebe4](https://github.com/Arize-ai/arize/commit/0caebe4e51883fdc2d6e61b06fe427eab0403390))
