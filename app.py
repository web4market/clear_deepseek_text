from flask import Flask, render_template, request, send_file
from bs4 import BeautifulSoup
import requests
import os
import re
import chardet
from urllib.parse import urlparse
from html import escape

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'output_files'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def detect_encoding(content):
    """Определяем кодировку контента"""
    result = chardet.detect(content)
    return result.get('encoding', 'utf-8')


def convert_to_utf8(text, original_encoding):
    """Конвертируем текст в UTF-8"""
    try:
        if original_encoding and original_encoding.lower() != 'utf-8':
            return text.encode(original_encoding).decode('utf-8', errors='ignore')
        return text
    except:
        return text


def clean_html(url):
    """Основная функция очистки HTML с правильной кодировкой"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # Определяем кодировку ответа
        encoding = response.encoding
        if not encoding:
            encoding = detect_encoding(response.content)

        # Декодируем с правильной кодировкой
        if encoding:
            html_content = response.content.decode(encoding, errors='replace')
        else:
            html_content = response.text

        # Используем html.parser (встроенный в BeautifulSoup) для избежания проблем с lxml
        soup = BeautifulSoup(html_content, 'html.parser')

        # Удаляем ненужные теги
        for tag in soup(['script', 'style', 'meta', 'link', 'noscript', 'iframe', 'svg', 'canvas']):
            tag.decompose()

        # Очищаем атрибуты
        for tag in soup.find_all(True):
            # Определяем разрешенные атрибуты для каждого тега
            allowed_attrs = []

            if tag.name == 'a':
                allowed_attrs = ['href', 'title', 'target']
            elif tag.name == 'img':
                allowed_attrs = ['src', 'alt', 'title']
            elif tag.name in ['table', 'tr', 'td', 'th']:
                allowed_attrs = ['colspan', 'rowspan']
            elif tag.name == 'input':
                allowed_attrs = ['type', 'name', 'value', 'placeholder']
            elif tag.name == 'form':
                allowed_attrs = ['action', 'method']

            # Сохраняем только разрешенные атрибуты
            attrs = dict(tag.attrs)
            tag.attrs = {}

            for attr in attrs:
                if attr in allowed_attrs:
                    tag[attr] = attrs[attr]

        # Получаем очищенный HTML
        cleaned_html = str(soup.prettify())

        # Убеждаемся, что это строка в UTF-8
        cleaned_html = cleaned_html.encode('utf-8', errors='replace').decode('utf-8')

        # Добавляем мета-тег с кодировкой в начало
        if '<meta charset=' not in cleaned_html[:500].lower() and '<meta http-equiv=' not in cleaned_html[:500].lower():
            head_start = cleaned_html.find('<head>')
            if head_start != -1:
                cleaned_html = cleaned_html[:head_start + 6] + '\n    <meta charset="UTF-8">' + cleaned_html[
                    head_start + 6:]
            else:
                html_start = cleaned_html.find('<html')
                if html_start != -1:
                    head_end = cleaned_html.find('>', html_start)
                    cleaned_html = cleaned_html[
                                       :head_end + 1] + '\n<head>\n    <meta charset="UTF-8">\n</head>' + cleaned_html[
                                       head_end + 1:]

        return cleaned_html

    except requests.exceptions.RequestException as e:
        return f"Ошибка при загрузке страницы: {str(e)}"
    except Exception as e:
        return f"Ошибка при обработке HTML: {str(e)}"


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('url', '').strip()

        if not url:
            return render_template('index.html', error="Введите URL страницы")

        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url

        try:
            result = clean_html(url)

            if result.startswith('Ошибка'):
                return render_template('index.html', error=result, url=url)

            # Создаем имя файла
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.replace('.', '_') if parsed_url.netloc else 'page'
            filename = f"{domain}_{os.urandom(4).hex()}.html"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # Сохраняем файл в UTF-8 с BOM для совместимости
            with open(filepath, 'w', encoding='utf-8-sig', errors='replace') as f:
                f.write(result)

            # Проверяем кодировку сохраненного файла
            with open(filepath, 'rb') as f:
                raw_content = f.read(1000)
                detected = chardet.detect(raw_content)
                print(f"Кодировка сохраненного файла: {detected['encoding']}")

            preview = escape(result[:1000]) + "..." if len(result) > 1000 else escape(result)
            return render_template('result.html',
                                   content=preview,
                                   filename=filename,
                                   url=url,
                                   file_size=len(result))

        except Exception as e:
            return render_template('index.html', error=f"Ошибка: {str(e)}", url=url)

    return render_template('index.html')


@app.route('/download/<filename>')
def download_file(filename):
    """Скачивание файла с указанием кодировки"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        return send_file(
            filepath,
            as_attachment=True,
            download_name=f"cleaned_{filename}",
            mimetype='text/html; charset=utf-8'
        )
    return "Файл не найден", 404


@app.route('/view/<filename>')
def view_file(filename):
    """Просмотр файла с правильными заголовками"""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        # Добавляем заголовки для правильного отображения кодировки
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Проверяем, есть ли уже мета-тег charset
        if '<meta charset=' not in content[:500].lower():
            # Добавляем заголовок Content-Type
            from flask import Response
            return Response(content, mimetype='text/html; charset=utf-8')

        return content
    return "Файл не найден", 404


@app.route('/test-encoding')
def test_encoding():
    """Тестовая страница для проверки кодировки"""
    test_text = "Тест русских букв: Привет мир! ✅ 🎉"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Тест кодировки</title>
    </head>
    <body>
        <h1>Тест UTF-8 кодировки</h1>
        <p>{test_text}</p>
        <p>Символы должны отображаться корректно.</p>
    </body>
    </html>
    """


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)