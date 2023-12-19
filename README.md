# Source
This project is based on ERP Next project https://github.com/frappe/erpnext. ERP Next is an open source ERP application that was built using Frappe Framework https://github.com/frappe/frappe

# How to deploy for the first time
1. Install Frappe framework https://frappeframework.com/docs/user/en/introduction. Note that Frappe framework needs Linux environment to run. If we use Windows we have to install Frappe framework on docker https://github.com/frappe/frappe_docker/blob/main/docs/development.md 
2. Install ERP Next App on frappe 
    * Fresh install `bench get-app --branch version-14 --resolve-deps erpnext`
    * Install from github (our modification) `bench get-app --branch version-12 https://github.com/myusername/myapp`
3. Create App `bench new-site development.localhost --mariadb-root-password 123 --admin-password admin --no-mariadb-socket --db-name frappedb`
4. Install ERP Next (App) on the site `bench --site development.localhost install-app erpnext`
5. Configure Procfile or run `sed -i '/redis/d' ./Procfile` to configure Procfile automatically
6. Setup DB configuration `common_site_config.json`
7. To run site
    * Run the site `bench start` (only for develompent, for production please read "Configure production")
    * You can also run project from launch.json using Visual Studio Code

# For developer
To enable developer mode, run this command
`bench --site development.localhost set-config developer_mode 1`
`bench --site development.localhost clear-cache`
Developer mode allow CMS to modify source code. For example, if we create new DocType, CMS will create new Doctype Code and the database. 

# How to deploy update (development)
This is not production standard, but it's ok for development
1. Stop service `bench stop`
2. Pull from git `git pull`
3. Do migration `bench migrate`
4. Start service `bench start`
For production setup, please read "Configure production"

# Configure production
Production setup will make sure service is always available although the server is restarted. Please read this tutorial to setup https://frappeframework.com/docs/user/en/bench/guides/setup-production