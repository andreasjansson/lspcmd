#include "user.hpp"
#include <iostream>
#include <memory>

using namespace example;

int main() {
    auto storage = std::make_unique<MemoryStorage>();
    UserRepository repo(std::move(storage));

    User user = createSampleUser();
    validateUser(user);

    repo.addUser(user);

    if (auto found = repo.getUser("john@example.com")) {
        std::cout << "Found user: " << found->displayName() << std::endl;
        std::cout << "Is adult: " << (found->isAdult() ? "yes" : "no") << std::endl;
    }

    return 0;
}
