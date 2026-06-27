git clone --bare https://github.com/ykim2718/yStudy_on_code_-_Python
cd yStudy_on_code_-_Python.git
# create new repositry on github page
git config --global http.postBuffer 3221225472  # Git 전송 버퍼 크기를 3GB으로 변경
git push --mirror https://github.com/ykim2718/Snippets.git
cd ..
Remove-Item -Path yStudy_on_code_-_Python.git -Recurse -Force