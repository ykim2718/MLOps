git init
git branch -M main
git remote add origin https://github.com/ROCKET/STATION.git

Add-Content -Path Hello.md -Value "Hello Git!"
git add Hello.md
git commit -m "first commit"
git push -u origin main