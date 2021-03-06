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

import pyfora.gpu

class GpuTestCases(object):
    def test_basic_gpu_apply(self):
        with self.create_executor() as fora:
            with fora.remotely:
                res = pyfora.gpu.map(lambda x: x+1, [1,2,3])

            result = res.toLocal().result()
            self.assertEqual(result, [2,3,4])

    def test_gpu_apply_large_vector(self):
        with self.create_executor() as fora:
            with fora.remotely:
                res = pyfora.gpu.map(lambda x: x+1, range(1000000))

            result = res.toLocal().result()

            self.assertEqual(result, [x+1 for x in range(1000000)])

    def test_basic_vec_in_vec(self):
        with self.create_executor() as fora:
            with fora.remotely:
                res = pyfora.gpu.map(lambda x: x[1], [[1,2,3],[2,3,4],[3,4,5]])

            result = res.toLocal().result()
            self.assertEqual(result, [2,3,4])
