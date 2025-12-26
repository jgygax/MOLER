class MockType(type):
    def __getattr__(cls, name):
        def mock_method(*args, **kwargs):
            return GenericMock()

        return mock_method


# Generic Mock class that can handle any function calls
class GenericMock(metaclass=MockType):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        def mock_method(*args, **kwargs):
            return GenericMock()

        return mock_method


class MockGPIO(GenericMock):
    pass
