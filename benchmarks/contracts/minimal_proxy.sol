pragma solidity ^0.8.0;
contract MinimalProxyFixture { address public implementation; constructor(address target) { implementation = target; } function target() external view returns (address) { return implementation; } }
