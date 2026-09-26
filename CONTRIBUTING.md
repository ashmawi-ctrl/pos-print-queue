# Contributing

Changes should be small enough to review and should describe the failure mode they address.

## Local setup

```bash
make install
make quality
```

## Workflow

1. Open or reference an issue that describes the behavior.
2. Create a focused branch such as `fix/...` or `feat/...`.
3. Add a regression test when the change fixes observable behavior.
4. Implement the smallest maintainable change.
5. Run `make quality`.
6. Open a pull request that explains:
   - the original failure mode
   - why the chosen behavior is safe
   - how it was tested
   - any remaining limitations

For printer delivery changes, explicitly discuss whether a retry can create duplicate physical output.
