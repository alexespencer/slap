# `slap check`

Check your project configuration for errors, warnings or recommendations.

## Configuration

Option scope: `[tool.slap.check]` or `[check]`

| Option | Type | Default | Description |
| ------ | ---- | ------- | ----------- |
| `plugins` | `list[str]` | `["changelog", "general", "poetry", "release"]` | A list of check plugins to use. Note that the Poetry plugin only fire checks if your project appears to be using Poetry, so there is no harm in leaving it enabled even if you don't it. Additional plugins can be registered via an `ApplicationPlugin` under the `CheckPlugin` group. |

---

## Built-in check plugins

@pydoc slap.ext.checks.changelog.ChangelogValidationCheckPlugin

@pydoc slap.ext.checks.general.GeneralChecksPlugin

@pydoc slap.ext.checks.poetry.PoetryChecksPlugin

@pydoc slap.ext.checks.release.ReleaseChecksPlugin
