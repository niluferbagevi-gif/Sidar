# managers/__init__.py Teknik Notu

Manager katmanının public API yüzeyini belirler.

## Dışa Aktarılanlar
- `CodeManager`
- `SystemHealthManager`
- `GitHubManager`
- `SecurityManager`
- `WebSearchManager`
- `PackageInfoManager`
- `TodoManager`

## Rolü

- Üst katmanın `from managers import ...` yoluyla kararlı import yapmasını sağlar.
- `__all__` sözleşmesiyle paket dışına açılan sınıfları açıkça sınırlar.
