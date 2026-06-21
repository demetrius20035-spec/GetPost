"""GetPost — графический клиент для HTTP-запросов (аналог Postman/Insomnia).

Пакет построен по схеме MVC:

* ``models``      — модель данных (Workspace → Folder → Request), без Qt;
* ``storage``     — сохранение/загрузка данных в JSON, без Qt;
* ``variables``   — подстановка переменных вида ``{{base_url}}``, без Qt;
* ``http_client`` — построение и выполнение HTTP-запросов (тестируемо), без Qt;
* ``runner``      — выполнение запроса в фоновом потоке (QThread);
* ``highlighter`` — подсветка синтаксиса JSON/XML;
* ``views``       — слой представления (GUI).
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
