eployPART-D

---

## 🚫 Blocking Comments (Must Fix Before Merging)

* **Secret printed in plain text:**  
  In the `Build image` step, `echo "Authenticating with token $REGISTRY_TOKEN"` prints our private token straight into the public CI run logs. Anyone who can see the run can steal the token. Also, `echo` doesn't actually log into Docker—we need `docker login` or the official login action.

* **Failing tests are ignored:**  
  The `Run tests` step uses `pytest tests/ || true`. The `|| true` part forces the step to succeed even when tests fail. Broken code will pass CI and get deployed directly to production.

* **SSH command will fail or hang:**  
  The `Deploy to production` step tries to `ssh` into the server, but there are no SSH keys added to the runner and no `known_hosts` configured. It will either throw a permission error or hang indefinitely waiting for manual confirmation.

* **Build happens before testing:**  
  We are building the container image before running unit tests. If tests fail, we just wasted CI minutes building an image we can't use. Testing needs to happen first.

---

## ⚠️ Non-Blocking Comments (Suggestions for Improvement)

* **Unpinned GitHub Action:**  
  Using `actions/checkout@master` pulls from a mutable branch. If upstream introduces breaking changes, our workflow could randomly break. We should pin this to a specific version like `@v4`.

* **Using only the `:latest` tag:**  
  Tagging the build only as `registry.example.com/grants:latest` makes rollbacks really messy if something breaks. We should tag images with the commit SHA (`${{ github.sha }}`) alongside `latest`.

* **Missing Python setup:**  
  `pytest` is called directly without setting up Python (`actions/setup-python`) or installing dependencies from `requirements.txt`. This might fail if the base runner environment changes.

* **Single-job pipeline:**  
  Everything runs in one sequential `deploy` job. It would be cleaner and easier to debug if we split this into separate jobs (`test`, `build`, `deploy`).

---

## ✅ Looks Good (Leave As Is)

* **`on: push: branches: [main]`**: Triggers automatically on pushes to `main`, which is standard for CD.
* **`runs-on: ubuntu-latest`**: Correct and standard runner choice for standard Docker/Linux workflows.
