import asyncio
import inspect


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run test in asyncio event loop")


def pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(testfunction(**kwargs))
        return True
    return None