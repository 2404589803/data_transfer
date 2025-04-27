# AutoDL 数据传输工具

这是一个用于将本地数据传输到 AutoDL 服务器的工具。使用 SFTP 协议，支持安全的文件传输。

## 功能特点

- 支持将本地文件传输到 AutoDL 服务器
- 支持整个文件夹的递归传输
- 支持所有类型的文件
- 实时显示传输进度和速度
- 支持 JSON 配置文件管理连接信息
- 详细的错误提示和连接状态显示
- 自动创建远程目录结构

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

1. 在项目根目录创建 `config.json` 文件，填入以下内容：
```json
{
    "host": "connect.nmb1.seetacloud.com",
    "port": 17980,
    "username": "root",
    "password": "你的密码"
}
```

配置说明：
- `host`: AutoDL 服务器地址
- `port`: SSH 端口号
- `username`: 用户名
- `password`: 密码

## 使用方法

1. 传输单个文件：
```bash
python main.py --local_path "本地文件路径" --remote_path "远程目标路径"
```

2. 传输整个文件夹：
```bash
python main.py --local_path "本地文件夹路径" --remote_path "远程目标路径"
```

示例：
```bash
# 传输单个文件
python main.py --local_path "D:/数据/测试.txt" --remote_path "/root/数据/测试.txt"

# 传输当前目录下的文件
python main.py --local_path "test.txt" --remote_path "/root/test.txt"

# 传输整个文件夹
python main.py --local_path "D:/我的数据" --remote_path "/root/我的数据"

# 传输当前目录下的文件夹
python main.py --local_path "./数据集" --remote_path "/root/数据集"
```

注意事项：
- 确保本地路径存在
- 远程路径需要有写入权限
- Windows 系统下路径可以使用正斜杠 `/` 或反斜杠 `\`
- 建议使用绝对路径以避免路径问题
- 传输文件夹时会自动创建远程目录结构
- 支持传输所有类型的文件，无格式限制

## 错误处理

如果遇到问题，程序会显示详细的错误信息：
- 配置文件不存在或格式错误
- 连接失败（网络问题）
- 身份验证失败（用户名或密码错误）
- 文件访问权限问题
- 远程目录创建失败

## 开发计划

- [x] 支持文件夹传输
- [ ] 支持断点续传
- [ ] 支持传输队列
- [ ] 支持传输速度限制
- [ ] 支持多文件并行传输 