/***************************************************************************
   Copyright 2016 Ufora Inc.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
****************************************************************************/
#include "FreeVariableMemberAccessChain.hpp"

#include <sstream>


FreeVariableMemberAccessChain::FreeVariableMemberAccessChain(
            const std::vector<std::string>& variables)
        : mVariables(variables)
    {
    }


std::string FreeVariableMemberAccessChain::str() const
    {
    std::ostringstream oss;
    for (size_type ix = 0; ix < mVariables.size(); ++ix)
        {
        if (ix != 0) {
            oss << ".";
            }
        oss << mVariables[ix];
        }
    return oss.str();
    }


bool operator<(const FreeVariableMemberAccessChain& l,
               const FreeVariableMemberAccessChain& r)
    {
    return l.mVariables < r.mVariables;
    }


bool operator==(const FreeVariableMemberAccessChain& l,
                const FreeVariableMemberAccessChain& r)
    {
    return l.mVariables == r.mVariables;
    }
