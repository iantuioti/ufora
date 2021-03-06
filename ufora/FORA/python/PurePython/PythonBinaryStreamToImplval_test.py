#   Copyright 2016 Ufora Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import unittest

import ufora.native.FORA as ForaNative
import ufora.native.CallbackScheduler as CallbackScheduler
import ufora.FORA.python.PurePython.Converter as Converter
import ufora.FORA.python.PurePython.PythonBinaryStreamToImplval as PythonBinaryStreamToImplval
import ufora.FORA.python.PurePython.PythonBinaryStreamFromImplval as PythonBinaryStreamFromImplval
import ufora.distributed.S3.InMemoryS3Interface as InMemoryS3Interface
import ufora.cumulus.test.InMemoryCumulusSimulation as InMemoryCumulusSimulation
import pyfora.BinaryObjectRegistry as BinaryObjectRegistry
import pyfora.PureImplementationMappings as PureImplementationMappings
import pyfora.PyObjectWalker as PyObjectWalker
from pyfora.PythonObjectRehydrator import PythonObjectRehydrator


class PythonBinaryStreamToImplvalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vdm = ForaNative.VectorDataManager(
            CallbackScheduler.singletonForTesting(), 10000000)

    @classmethod
    def tearDownClass(cls):
        if cls.vdm is not None:
            cls.vdm.teardown()
            cls.vdm = None

    def test_deserialize_primitives(self):
        for value in [1,1.0,"1.0",None,False, [], [1.0], [1.0], {1:2}, (1,2,3)]:
            self.assertEqual(value, self.roundtripConvert(value))

    def test_deserialize_singletons(self):
        for value in [str, list]:
            self.assertTrue(value is self.roundtripConvert(value))

    def test_deserialize_basic_functions(self):
        def f(x):
            return x + 1

        f2 = self.roundtripConvert(f)

        assert f(10) == f2(10)

    def test_deserialize_basic_functions_with_capture(self):
        def g(x):
            return x + 2
        def f(x):
            return g(x) + 1

        f2 = self.roundtripConvert(f)

        assert f(10) == f2(10)

    def test_deserialize_lambda_functions(self):
        g = lambda x: x + 2

        def f(x):
            return g(x) + 1

        f2 = self.roundtripConvert(f)

        assert f(10) == f2(10)

    def test_deserialize_classes(self):
        def g(x):
            return x + 2
        def f(x):
            return g(x) + 1

        class ABase:
            def r(self, z):
                return z+1

        class C(ABase):
            def q(self, x):
                return f(x+1)

        C2 = self.roundtripConvert(C)

        assert C2().q(10) == C().q(10)
        assert C2().r(10) == C().r(10)

    def test_deserialize_class_instances(self):
        def g(x):
            return x + 2
        def f(x):
            return g(x) + 1

        class ABase_2:
            def r(self, z):
                return z+1

        class C_2(ABase_2):
            def q(self, x):
                return f(x+1)

        c = C_2()
        c2 = self.roundtripConvert(c)

        assert c2.q(10) == c.q(10)
        assert c2.r(10) == c.r(10)

    def test_execute_function_in_pyfora(self):
        def f(x):
            return x + 1

        self.assertEqual(self.roundtripExecute(f,2), f(2))

    def test_execute_mutually_recursive_functions(self):
        def g(x):
            if x > 1:
                return f(x-1) + 2
            return 1

        def f(x):
            if x > 1:
                return g(x-1) + 3
            return x + 1

        self.assertEqual(self.roundtripExecute(f,10), f(10))

    def test_execute_mutually_recursive_functions_overlapping_names(self):
        def make_g(f,y):
            def g(x):
                if x > 1:
                    return f(x-1) + y
                return 1
            return g

        y = 10
        def f(x):
            if x > 1:
                return g(x-1) + y
            return x + 1
        
        g = make_g(f, 3)


        self.assertEqual(self.roundtripExecute(f,10), f(10))

    def roundtripConvert(self, pyObject):
        mappings = PureImplementationMappings.PureImplementationMappings()
        binaryObjectRegistry = BinaryObjectRegistry.BinaryObjectRegistry()

        walker = PyObjectWalker.PyObjectWalker(
            mappings,
            binaryObjectRegistry
            )

        root_id = walker.walkPyObject(pyObject)
        binaryObjectRegistry.defineEndOfStream()

        data = binaryObjectRegistry.str()

        streamReader = PythonBinaryStreamToImplval.constructConverter(
            Converter.canonicalPurePythonModule(), self.vdm)

        streamReader.read(data)
        anObjAsImplval = streamReader.getObjectById(root_id)
    
        converter = PythonBinaryStreamFromImplval.constructConverter(
            Converter.canonicalPurePythonModule(), self.vdm)

        root_id, data = converter.write(anObjAsImplval)

        rehydrator = PythonObjectRehydrator(
            mappings, allowUserCodeModuleLevelLookups=False)

        return rehydrator.convertEncodedStringToPythonObject(data, root_id)


    def roundtripExecute(self, pyObject, *args):
        mappings = PureImplementationMappings.PureImplementationMappings()
        binaryObjectRegistry = BinaryObjectRegistry.BinaryObjectRegistry()

        walker = PyObjectWalker.PyObjectWalker(
            mappings,
            binaryObjectRegistry
            )

        ids = [walker.walkPyObject(o) for o in [pyObject] + list(args)]
        binaryObjectRegistry.defineEndOfStream()

        data = binaryObjectRegistry.str()

        streamReader = PythonBinaryStreamToImplval.constructConverter(
            Converter.canonicalPurePythonModule(), self.vdm)

        streamReader.read(data)

        implVals = [streamReader.getObjectById(i) for i in ids]

        result = InMemoryCumulusSimulation.computeUsingSeveralWorkers(
            ForaNative.ImplValContainer(
                (implVals[0],
                ForaNative.makeSymbol("Call")) + 
                tuple(implVals[1:])
                ),
            InMemoryS3Interface.InMemoryS3InterfaceFactory(),
            1
            )

        self.assertTrue(result.isResult(), result)

        result = result.asResult.result

        converter = PythonBinaryStreamFromImplval.constructConverter(
            Converter.canonicalPurePythonModule(), self.vdm)
    
        root_id, data = converter.write(result)

        rehydrator = PythonObjectRehydrator(
            mappings, allowUserCodeModuleLevelLookups=False)

        return rehydrator.convertEncodedStringToPythonObject(data, root_id)

