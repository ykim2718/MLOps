pip install git-filter-repo
git config --global core.longpaths true
git clone https://github.com/ykim2718/yStudy_on_code_-_Python python_snippets
cd python_snippets
# git filter-repo --path "Python - Snippets/yPython on Modules/" --path "Python - Snippets/yPython on Grammar/"
python -m git_filter_repo --path "Python - Snippets/yPython on Modules/" --path "Python - Snippets/yPython on Python Grammar/"
git remote add origin https://github.com/ykim2718/Python_snippets.git
git branch -M main
git push -u origin main
git status -v