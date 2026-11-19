@echo off
chcp 65001 >nul
REM ============================================================
REM DTC 平台 - 首次推送到 GitHub 脚本
REM 使用前先在 GitHub 网页创建一个空仓库（如 dtc-platform），
REM 然后按提示输入你的用户名、仓库名和邮箱。
REM 本脚本只在本次命令中临时指定提交身份，不修改全局 git 配置。
REM ============================================================

set "GH_USER=W17067728505"
set /p GH_REPO="仓库名 (直接回车用默认 dtc-direct-platform): "
if "%GH_REPO%"=="" set "GH_REPO=dtc-direct-platform"
set /p GH_EMAIL="提交邮箱 (直接回车用默认): "
if "%GH_EMAIL%"=="" set "GH_EMAIL=W17067728505@users.noreply.github.com"

cd /d %~dp0

REM 首次提交（临时身份，不写入 git config）
git -c user.name="%GH_USER%" -c user.email="%GH_EMAIL%" commit -m "Initial DTC MVP with viral growth" 2>nul
if errorlevel 1 (
  echo 没有可提交的新变更，可能已提交过，继续...
)

REM 关联远程仓库（若已存在则忽略错误）
git remote remove origin 2>nul
git remote add origin https://github.com/%GH_USER%/%GH_REPO%.git

REM 推送（分支 main）
git branch -M main
echo 正在推送到 https://github.com/%GH_USER%/%GH_REPO%.git
git push -u origin main

echo.
echo 完成后：到 Render 用该仓库创建 Web Service，会自动读取 render.yaml。
pause
