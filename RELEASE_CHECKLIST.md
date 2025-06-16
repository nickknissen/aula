# Release Checklist

## Pre-Release

- [ ] Ensure all tests are passing:
  ```bash
  pytest
  ```
- [ ] Update `CHANGELOG.md` with the new version and changes
- [ ] Update the version number in `pyproject.toml`
- [ ] Ensure all new features are documented in the appropriate `.md` files
- [ ] Run linters and fix any issues:
  ```bash
  black .
  ruff check --fix .
  ```

## Release Process

1. Create a release branch:
   ```bash
   git checkout -b release/vX.Y.Z
   ```

2. Commit the version bump and changelog updates:
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "Bump version to vX.Y.Z"
   ```

3. Build the package:
   ```bash
   python -m build
   ```

4. Test the built package:
   ```bash
   # Create a clean virtual environment
   python -m venv test-env
   source test-env/bin/activate  # On Windows: test-env\Scripts\activate
   
   # Install the package
   pip install dist/aula-X.Y.Z.tar.gz
   
   # Test the installation
   aula --version
   ```

5. Tag the release:
   ```bash
   git tag -a vX.Y.Z -m "Version X.Y.Z"
   git push origin vX.Y.Z
   ```

6. Publish to PyPI:
   ```bash
   twine upload dist/*
   ```

7. Create a GitHub release:
   - Go to the repository's Releases page
   - Click "Draft a new release"
   - Select the tag you just pushed
   - Set the release title to "vX.Y.Z"
   - Add release notes from CHANGELOG.md
   - Attach the built distribution files from the `dist/` directory
   - Publish the release

8. Merge the release branch into main:
   ```bash
   git checkout main
   git merge --no-ff release/vX.Y.Z
   git push origin main
   ```

9. Clean up:
   ```bash
   git branch -d release/vX.Y.Z
   git push origin --delete release/vX.Y.Z
   ```

## Post-Release

- [ ] Update any documentation that references the version number
- [ ] Announce the release (if applicable)
- [ ] Monitor for any issues reported by users

## Versioning

This project follows [Semantic Versioning](https://semver.org/):

- **MAJOR** version for incompatible API changes
- **MINOR** version for added functionality in a backward-compatible manner
- **PATCH** version for backward-compatible bug fixes
