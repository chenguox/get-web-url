from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import time
import logging
from urllib.parse import urljoin, urlparse
import uuid
from werkzeug.utils import secure_filename

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 确保目录存在
IMAGES_DIR = os.path.join('static', 'images')
DOWNLOADS_DIR = 'downloads'
UPLOAD_FOLDER = 'uploads'
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 允许的文件类型
ALLOWED_EXTENSIONS = {'html', 'htm'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_html_content(html_content, base_url=None):
    """处理HTML内容,提取链接、标题和图片"""
    soup = BeautifulSoup(html_content, 'html.parser')
    data = []
    count = 0
    
    # 获取所有链接
    links = soup.find_all('a')
    logger.info(f"找到 {len(links)} 个链接")
    
    for link in links:
        # 查找该链接下的标题和图片
        title_elem = link.find(class_='item-title')
        image_elem = link.find(class_='item-image')
        
        # 如果找到了标题和图片，则处理该条数据
        if title_elem and image_elem:
            count += 1
            title = title_elem.text.strip()
            
            # 优先使用data-url属性，如果没有则使用href属性
            link_url = link.get('data-url', '') or link.get('href', '')
            
            # 确保链接是完整的URL
            if base_url and link_url and not link_url.startswith(('http://', 'https://')):
                link_url = urljoin(base_url, link_url)
            
            # 获取图片URL
            img_url = None
            img_tag = image_elem.find('img')
            if img_tag:
                # 优先使用data-src属性,如果没有则使用src属性
                img_url = img_tag.get('data-src', '') or img_tag.get('src', '')
                if base_url and img_url and not img_url.startswith(('http://', 'https://')):
                    img_url = urljoin(base_url, img_url)
            
            # 生成安全的文件名
            safe_title = "".join([c if c.isalnum() or c in ' .-_' else '_' for c in title])
            if not safe_title:
                safe_title = str(uuid.uuid4())[:8]  # 使用UUID如果标题为空或无法使用
            
            # 下载并保存图片
            img_filename = None
            if img_url:
                try:
                    if base_url:  # 如果是远程URL
                        img_response = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        img_response.raise_for_status()
                        img_content = img_response.content
                    else:  # 如果是本地文件
                        img_path = os.path.join(os.path.dirname(base_url), img_url)
                        if os.path.exists(img_path):
                            with open(img_path, 'rb') as f:
                                img_content = f.read()
                        else:
                            logger.error(f"本地图片不存在: {img_path}")
                            continue
                    
                    # 从URL中获取文件扩展名
                    img_ext = os.path.splitext(urlparse(img_url).path)[1]
                    if not img_ext:
                        img_ext = '.jpg'  # 默认扩展名
                    
                    img_filename = f"{safe_title}{img_ext}"
                    img_path = os.path.join(IMAGES_DIR, img_filename)
                    
                    with open(img_path, 'wb') as f:
                        f.write(img_content)
                    
                    logger.info(f"已保存图片: {img_filename}")
                except Exception as e:
                    logger.error(f"下载图片时出错: {e}")
                    img_filename = None
            
            # 添加到数据列表
            data.append({
                'title': title,
                'url': link_url,
                'image': img_filename
            })
            
            logger.info(f"已处理 {count} 个站点: {title}")
    
    return data

@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    """爬取网站链接、标题和图片"""
    try:
        # 获取前端传递的URL
        url = request.json.get('url', '')
        if not url:
            return jsonify({'success': False, 'message': '请提供有效的URL'})
        
        logger.info(f"开始爬取网站: {url}")
        
        # 发送HTTP请求获取网页内容
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 如果请求失败，抛出异常
        
        # 处理HTML内容
        data = process_html_content(response.content, url)
        
        if not data:
            return jsonify({'success': False, 'message': '未找到符合条件的数据，请检查网站结构'})
        
        # 生成Excel文件
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        excel_filename = f'website_data_{timestamp}.xlsx'
        excel_path = os.path.join(DOWNLOADS_DIR, excel_filename)
        
        # 创建DataFrame并保存为Excel
        df = pd.DataFrame(data)
        df = df[['title', 'url', 'image']]  # 调整列顺序
        df.columns = ['网站标题', '链接地址', '图片文件名']
        df.to_excel(excel_path, index=False)
        
        logger.info(f"生成Excel文件: {excel_filename}")
        
        return jsonify({
            'success': True, 
            'message': f'成功爬取 {len(data)} 个网站数据',
            'data': data,
            'excel_file': excel_filename
        })
    
    except requests.exceptions.RequestException as e:
        logger.error(f"请求错误: {e}")
        return jsonify({'success': False, 'message': f'网站请求失败: {str(e)}'})
    except Exception as e:
        logger.error(f"未知错误: {e}")
        return jsonify({'success': False, 'message': f'发生错误: {str(e)}'})

@app.route('/upload', methods=['POST'])
def upload_file():
    """处理本地HTML文件上传"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '没有上传文件'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': '没有选择文件'})
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'message': '不支持的文件类型'})
        
        # 保存上传的文件
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        
        logger.info(f"已保存上传的文件: {filename}")
        
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # 处理HTML内容
        data = process_html_content(html_content, file_path)
        
        if not data:
            return jsonify({'success': False, 'message': '未找到符合条件的数据，请检查文件内容'})
        
        # 生成Excel文件
        timestamp = time.strftime('%Y%m%d_%H%M%S')
        excel_filename = f'website_data_{timestamp}.xlsx'
        excel_path = os.path.join(DOWNLOADS_DIR, excel_filename)
        
        # 创建DataFrame并保存为Excel
        df = pd.DataFrame(data)
        df = df[['title', 'url', 'image']]  # 调整列顺序
        df.columns = ['网站标题', '链接地址', '图片文件名']
        df.to_excel(excel_path, index=False)
        
        logger.info(f"生成Excel文件: {excel_filename}")
        
        # 删除上传的文件
        os.remove(file_path)
        
        return jsonify({
            'success': True, 
            'message': f'成功处理 {len(data)} 个网站数据',
            'data': data,
            'excel_file': excel_filename
        })
        
    except Exception as e:
        logger.error(f"处理文件时出错: {e}")
        return jsonify({'success': False, 'message': f'处理文件时出错: {str(e)}'})

@app.route('/download/<filename>')
def download_file(filename):
    """下载生成的Excel文件"""
    try:
        file_path = os.path.join(DOWNLOADS_DIR, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        else:
            return jsonify({'success': False, 'message': '文件不存在'})
    except Exception as e:
        logger.error(f"下载文件时出错: {e}")
        return jsonify({'success': False, 'message': f'下载失败: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True) 